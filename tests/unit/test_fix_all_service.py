import copy

import pytest

import routers.projects as projects_router
import services.fix_all as fix_all_module
from models.schemas import FindingTransform
from services.fix_all import get_fix_all_status, is_fix_all_running, request_stop, start_fix_all
from services.groq_client import GroqUnavailableError
from services.patching import PatchError

OWNER = "demo-user"


def _finding(finding_id, file, evidence, rule="hardcoded_secret", severity="critical", line=1):
    return {
        "finding_id": finding_id,
        "file": file,
        "line": line,
        "rule": rule,
        "rule_id": rule,
        "severity": severity,
        "evidence": evidence,
        "message": f"{rule} issue",
        "category": "security",
    }


def _file(path, content, language="python"):
    return {"path": path, "content": content, "language": language}


def _project(findings, files, source_revision=1, analysis_status="completed"):
    return {
        "_id": "proj-1",
        "owner_user_id": OWNER,
        "security_findings": copy.deepcopy(findings),
        "findings": copy.deepcopy(findings),
        "files": copy.deepcopy(files),
        "patches": [],
        "source_revision": source_revision,
        "analysis_status": analysis_status,
        "project": {"name": "demo", "frameworks": []},
    }


class _FakeDB:
    def __init__(self, project):
        self.projects = {project["_id"]: project}

    async def get_owned_project(self, project_id, owner_user_id):
        doc = self.projects.get(project_id)
        if doc is None or doc.get("owner_user_id") != owner_user_id:
            return None
        return copy.deepcopy(doc)

    async def update_owned_project(self, project_id, owner_user_id, updates, *, expected_source_revision=None):
        doc = self.projects.get(project_id)
        if doc is None or doc.get("owner_user_id") != owner_user_id:
            return False
        if expected_source_revision is not None and int(doc.get("source_revision", 0)) != expected_source_revision:
            return False
        doc.update(copy.deepcopy(updates))
        return True


@pytest.fixture(autouse=True)
def _reset_active_runs():
    fix_all_module._active_runs.clear()
    yield
    fix_all_module._active_runs.clear()


def _install_db(monkeypatch, project):
    db = _FakeDB(project)
    monkeypatch.setattr(fix_all_module, "get_owned_project", db.get_owned_project)
    monkeypatch.setattr(fix_all_module, "update_owned_project", db.update_owned_project)
    return db


def _stub_reanalysis(monkeypatch, db, project_id, *, after_findings=None, raises=None):
    """Replace the lazily-imported canonical reanalysis pipeline with a
    controllable stub -- exercising the real Groq-backed pipeline in a unit
    test isn't the point here; what matters is that fix_all treats its
    result as the sole source of truth for after_count."""

    async def fake_run_project_analysis(pid, owner_user_id):
        if raises is not None:
            raise raises
        doc = db.projects[pid]
        doc["security_findings"] = after_findings if after_findings is not None else []
        doc["findings"] = doc["security_findings"]
        doc["analysis_status"] = "completed"
        return {"project_id": pid, "finding_count": len(doc["security_findings"])}

    monkeypatch.setattr(projects_router, "_run_project_analysis", fake_run_project_analysis)


async def _run_now(project_id, owner_user_id):
    state = {
        "job_id": "test-job",
        "status": "running",
        "stop_requested": False,
        "total": 0,
        "processed": 0,
        "results": [],
        "report": None,
        "error": None,
    }
    await fix_all_module._run(project_id, owner_user_id, state)
    return state


def _mock_generate_fix(monkeypatch, transforms_by_finding_id, on_call=None):
    async def fake_generate_fix(finding, code_snippet, language, standards, related_files=None, knowledge=None):
        if on_call is not None:
            on_call(finding, code_snippet)
        outcome = transforms_by_finding_id[finding["finding_id"]]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(fix_all_module, "generate_fix", fake_generate_fix)


# --------------------------------------------------------------- scenario 1

@pytest.mark.asyncio
async def test_multiple_findings_across_different_files(monkeypatch):
    findings = [
        _finding("f1", "a.py", 'API_KEY = "hardcoded-secret-value-123"'),
        _finding("f2", "b.py", "cursor.execute(query)", rule="sql_concat", severity="high"),
    ]
    files = [
        _file("a.py", 'API_KEY = "hardcoded-secret-value-123"\n'),
        _file("b.py", "query = build_query()\ncursor.execute(query)\n"),
    ]
    project = _project(findings, files)
    db = _install_db(monkeypatch, project)
    _stub_reanalysis(monkeypatch, db, "proj-1", after_findings=[])
    _mock_generate_fix(monkeypatch, {
        "f1": FindingTransform(original_snippet='API_KEY = "hardcoded-secret-value-123"', proposed_fix='API_KEY = os.environ["API_KEY"]'),
        "f2": FindingTransform(original_snippet="cursor.execute(query)", proposed_fix="cursor.execute(query, params)"),
    })

    state = await _run_now("proj-1", OWNER)

    assert state["status"] == "completed"
    statuses = {r["finding_id"]: r["status"] for r in state["report"]["results"]}
    assert statuses == {"f1": "fixed", "f2": "fixed"}
    assert db.projects["proj-1"]["files"][0]["content"] == 'API_KEY = os.environ["API_KEY"]\n'
    assert "cursor.execute(query, params)" in db.projects["proj-1"]["files"][1]["content"]
    assert db.projects["proj-1"]["source_revision"] == 3  # two applied patches


# --------------------------------------------------------------- scenario 2

@pytest.mark.asyncio
async def test_multiple_findings_same_file(monkeypatch):
    content = 'API_KEY = "hardcoded-secret-value-123"\ndef handler(cmd):\n    subprocess.run(cmd, shell=True)\n'
    findings = [
        _finding("f1", "app.py", 'API_KEY = "hardcoded-secret-value-123"'),
        _finding("f2", "app.py", "subprocess.run(cmd, shell=True)", rule="subprocess_shell_true", severity="high", line=3),
    ]
    project = _project(findings, [_file("app.py", content)])
    db = _install_db(monkeypatch, project)
    _stub_reanalysis(monkeypatch, db, "proj-1", after_findings=[])
    _mock_generate_fix(monkeypatch, {
        "f1": FindingTransform(original_snippet='API_KEY = "hardcoded-secret-value-123"', proposed_fix='API_KEY = os.environ["API_KEY"]'),
        "f2": FindingTransform(original_snippet="subprocess.run(cmd, shell=True)", proposed_fix="subprocess.run(cmd, shell=False)"),
    })

    state = await _run_now("proj-1", OWNER)

    final_content = db.projects["proj-1"]["files"][0]["content"]
    assert 'os.environ["API_KEY"]' in final_content
    assert "shell=False" in final_content
    assert all(r["status"] == "fixed" for r in state["report"]["results"])
    assert db.projects["proj-1"]["source_revision"] == 3


# --------------------------------------------------------------- scenario 3

@pytest.mark.asyncio
async def test_second_fix_is_generated_against_updated_source(monkeypatch):
    content = "MARKER_BEFORE_FIX = 1\nAPI_KEY = \"hardcoded-secret-value-123\"\n"
    findings = [
        _finding("f1", "app.py", 'API_KEY = "hardcoded-secret-value-123"'),
        _finding("f2", "app.py", "MARKER_BEFORE_FIX = 1", rule="dangerous_eval", severity="high"),
    ]
    project = _project(findings, [_file("app.py", content)])
    db = _install_db(monkeypatch, project)
    _stub_reanalysis(monkeypatch, db, "proj-1", after_findings=[])

    seen_snippets = {}

    def capture(finding, code_snippet):
        seen_snippets[finding["finding_id"]] = code_snippet

    _mock_generate_fix(monkeypatch, {
        "f1": FindingTransform(original_snippet='API_KEY = "hardcoded-secret-value-123"', proposed_fix='API_KEY = os.environ["API_KEY"]'),
        "f2": FindingTransform(original_snippet="MARKER_BEFORE_FIX = 1", proposed_fix="MARKER_AFTER_FIX = 1"),
    }, on_call=capture)

    await _run_now("proj-1", OWNER)

    # f2's own evidence line is untouched by f1's patch, so f2 still gets
    # processed for real -- but the snippet it was generated from must come
    # from the file AFTER f1 was applied, not the original upload.
    assert "hardcoded-secret-value-123" not in seen_snippets["f2"]


# --------------------------------------------------------------- scenario 4

@pytest.mark.asyncio
async def test_first_fix_indirectly_resolves_second_finding(monkeypatch):
    content = (
        "def handler(request):\n"
        "    API_KEY = \"hardcoded-secret-value-123\"\n"
        "    return API_KEY\n"
    )
    # f2's "evidence" is a substring inside the exact block f1's patch removes.
    findings = [
        _finding("f1", "app.py", "API_KEY = \"hardcoded-secret-value-123\"\n    return API_KEY", rule="hardcoded_secret"),
        _finding("f2", "app.py", "return API_KEY", rule="sensitive_return", severity="low", line=3),
    ]
    project = _project(findings, [_file("app.py", content)])
    db = _install_db(monkeypatch, project)
    _stub_reanalysis(monkeypatch, db, "proj-1", after_findings=[])

    calls = []

    def capture(finding, code_snippet):
        calls.append(finding["finding_id"])

    _mock_generate_fix(monkeypatch, {
        "f1": FindingTransform(
            original_snippet="API_KEY = \"hardcoded-secret-value-123\"\n    return API_KEY",
            proposed_fix="API_KEY = os.environ[\"API_KEY\"]\n    return \"[redacted]\"",
        ),
        "f2": Exception("must not be called -- f2 should resolve indirectly"),
    }, on_call=capture)

    state = await _run_now("proj-1", OWNER)

    results = {r["finding_id"]: r for r in state["report"]["results"]}
    assert results["f1"]["status"] == "fixed"
    assert results["f2"]["status"] == "already_resolved"
    assert "f2" not in calls  # generate_fix was never invoked for the indirectly-resolved finding


# --------------------------------------------------------------- scenario 5

@pytest.mark.asyncio
async def test_malformed_generated_patch_is_marked_failed(monkeypatch):
    findings = [_finding("f1", "app.py", 'API_KEY = "hardcoded-secret-value-123"')]
    project = _project(findings, [_file("app.py", 'API_KEY = "hardcoded-secret-value-123"\n')])
    db = _install_db(monkeypatch, project)
    _stub_reanalysis(monkeypatch, db, "proj-1", after_findings=findings)
    _mock_generate_fix(monkeypatch, {
        "f1": FindingTransform(original_snippet="this text does not exist in the file at all", proposed_fix="anything"),
    })

    state = await _run_now("proj-1", OWNER)

    result = state["report"]["results"][0]
    assert result["status"] == "failed"
    assert db.projects["proj-1"]["files"][0]["content"] == 'API_KEY = "hardcoded-secret-value-123"\n'  # untouched
    assert db.projects["proj-1"]["source_revision"] == 1  # no revision bump on failure


# --------------------------------------------------------------- scenario 6

@pytest.mark.asyncio
async def test_provider_failure_on_one_finding_does_not_kill_the_queue(monkeypatch):
    findings = [
        _finding("f1", "a.py", 'API_KEY = "hardcoded-secret-value-123"'),
        _finding("f2", "b.py", "cursor.execute(query)", rule="sql_concat", severity="high"),
    ]
    files = [_file("a.py", 'API_KEY = "hardcoded-secret-value-123"\n'), _file("b.py", "cursor.execute(query)\n")]
    project = _project(findings, files)
    db = _install_db(monkeypatch, project)
    _stub_reanalysis(monkeypatch, db, "proj-1", after_findings=[])
    _mock_generate_fix(monkeypatch, {
        "f1": FindingTransform(original_snippet='API_KEY = "hardcoded-secret-value-123"', proposed_fix='API_KEY = os.environ["API_KEY"]'),
        "f2": GroqUnavailableError("all keys exhausted"),
    })

    state = await _run_now("proj-1", OWNER)

    results = {r["finding_id"]: r for r in state["report"]["results"]}
    assert results["f1"]["status"] == "fixed"
    assert results["f2"]["status"] == "failed"
    assert "unavailable" in results["f2"]["message"].lower()
    assert state["report"]["fixed"] == 1
    assert state["report"]["failed"] == 1


# --------------------------------------------------------------- scenario 7

@pytest.mark.asyncio
async def test_patch_validation_failure_is_isolated(monkeypatch):
    findings = [_finding("f1", "app.py", 'API_KEY = "hardcoded-secret-value-123"')]
    project = _project(findings, [_file("app.py", 'API_KEY = "hardcoded-secret-value-123"\n')])
    db = _install_db(monkeypatch, project)
    _stub_reanalysis(monkeypatch, db, "proj-1", after_findings=findings)
    _mock_generate_fix(monkeypatch, {
        "f1": FindingTransform(original_snippet='API_KEY = "hardcoded-secret-value-123"', proposed_fix='API_KEY = os.environ["API_KEY"]'),
    })

    def raise_patch_error(*args, **kwargs):
        raise PatchError("source changed underneath the patch")

    monkeypatch.setattr(fix_all_module, "apply_structured_patch", raise_patch_error)

    state = await _run_now("proj-1", OWNER)

    result = state["report"]["results"][0]
    assert result["status"] == "failed"
    assert "could not be applied" in result["message"].lower()
    assert db.projects["proj-1"]["source_revision"] == 1


# --------------------------------------------------------------- scenario 9

@pytest.mark.asyncio
async def test_user_stops_mid_run(monkeypatch):
    findings = [
        _finding("f1", "a.py", 'API_KEY = "hardcoded-secret-value-123"'),
        _finding("f2", "b.py", "x", rule="dangerous_eval", severity="high"),
        _finding("f3", "c.py", "y", rule="dangerous_eval", severity="high"),
    ]
    files = [_file("a.py", 'API_KEY = "hardcoded-secret-value-123"\n'), _file("b.py", "x\n"), _file("c.py", "y\n")]
    project = _project(findings, files)
    db = _install_db(monkeypatch, project)
    _stub_reanalysis(monkeypatch, db, "proj-1", after_findings=[])

    state = {
        "job_id": "test-job", "status": "running", "stop_requested": False,
        "total": 0, "processed": 0, "results": [], "report": None, "error": None,
    }

    async def fake_generate_fix(finding, code_snippet, language, standards, related_files=None, knowledge=None):
        if finding["finding_id"] == "f1":
            state["stop_requested"] = True  # simulate the user clicking Stop while f1 is in flight
        return FindingTransform(original_snippet=finding["evidence"], proposed_fix="fixed")

    monkeypatch.setattr(fix_all_module, "generate_fix", fake_generate_fix)

    await fix_all_module._run("proj-1", OWNER, state)

    results = {r["finding_id"]: r for r in state["report"]["results"]}
    assert results["f1"]["status"] == "fixed"  # in-flight patch completes, never interrupted halfway
    assert results["f2"]["status"] == "skipped"
    assert results["f3"]["status"] == "skipped"
    assert state["report"]["stopped_early"] is True
    assert state["report"]["status"] in ("completed", "completed_verification_failed")  # reanalysis still ran


# -------------------------------------------------------------- scenario 10

@pytest.mark.asyncio
async def test_final_reanalysis_changes_finding_count(monkeypatch):
    findings = [_finding("f1", "app.py", 'API_KEY = "hardcoded-secret-value-123"')]
    project = _project(findings, [_file("app.py", 'API_KEY = "hardcoded-secret-value-123"\n')])
    db = _install_db(monkeypatch, project)
    _stub_reanalysis(monkeypatch, db, "proj-1", after_findings=[])  # fix genuinely resolved it
    _mock_generate_fix(monkeypatch, {
        "f1": FindingTransform(original_snippet='API_KEY = "hardcoded-secret-value-123"', proposed_fix='API_KEY = os.environ["API_KEY"]'),
    })

    state = await _run_now("proj-1", OWNER)

    assert state["report"]["before_count"] == 1
    assert state["report"]["after_count"] == 0


# -------------------------------------------------------------- scenario 11

@pytest.mark.asyncio
async def test_final_reanalysis_failure_is_reported_without_false_success(monkeypatch):
    findings = [_finding("f1", "app.py", 'API_KEY = "hardcoded-secret-value-123"')]
    project = _project(findings, [_file("app.py", 'API_KEY = "hardcoded-secret-value-123"\n')])
    db = _install_db(monkeypatch, project)
    _stub_reanalysis(monkeypatch, db, "proj-1", raises=RuntimeError("mongo unavailable"))
    _mock_generate_fix(monkeypatch, {
        "f1": FindingTransform(original_snippet='API_KEY = "hardcoded-secret-value-123"', proposed_fix='API_KEY = os.environ["API_KEY"]'),
    })

    state = await _run_now("proj-1", OWNER)

    assert state["report"]["status"] == "completed_verification_failed"
    assert state["report"]["verification_note"] == "Fixes were applied, but final verification could not complete."
    # The patch itself is NOT lost even though verification failed.
    assert 'os.environ["API_KEY"]' in db.projects["proj-1"]["files"][0]["content"]


# -------------------------------------------------------------- scenario 12

@pytest.mark.asyncio
async def test_zero_findings_short_circuits_cleanly(monkeypatch):
    project = _project([], [_file("app.py", "print('clean')\n")])
    _install_db(monkeypatch, project)

    state = await _run_now("proj-1", OWNER)

    assert state["status"] == "completed"
    assert state["report"]["results"] == []
    assert state["report"]["before_count"] == 0


# -------------------------------------------------------------- scenario 13

@pytest.mark.asyncio
async def test_duplicate_fix_all_click_returns_the_same_running_job(monkeypatch):
    findings = [_finding("f1", "app.py", 'API_KEY = "hardcoded-secret-value-123"')]
    project = _project(findings, [_file("app.py", 'API_KEY = "hardcoded-secret-value-123"\n')])
    _install_db(monkeypatch, project)

    async def never_returns(*args, **kwargs):
        import asyncio as _asyncio
        await _asyncio.sleep(3600)

    monkeypatch.setattr(fix_all_module, "generate_fix", never_returns)

    first = await start_fix_all("proj-1", OWNER)
    second = await start_fix_all("proj-1", OWNER)

    assert first["job_id"] == second["job_id"]
    assert is_fix_all_running("proj-1") is True


# -------------------------------------------------------------- scenario 14

def test_manual_fix_blocked_while_fix_all_is_running():
    fix_all_module._active_runs["proj-x"] = {"status": "running", "job_id": "j1"}
    assert is_fix_all_running("proj-x") is True
    fix_all_module._active_runs["proj-x"]["status"] = "completed"
    assert is_fix_all_running("proj-x") is False


def test_request_stop_only_affects_a_running_job():
    assert request_stop("no-such-project") is False
    fix_all_module._active_runs["proj-y"] = {"status": "running", "job_id": "j2", "stop_requested": False}
    assert request_stop("proj-y") is True
    assert fix_all_module._active_runs["proj-y"]["stop_requested"] is True
    fix_all_module._active_runs["proj-y"]["status"] = "completed"
    assert request_stop("proj-y") is False
