import copy

import pytest

import services.commit_guard as commit_guard_module
from services.commit_guard import (
    _build_report_shape,
    _compute_verdict,
    _docs_only_result,
    _run,
    _static_validity,
    is_commit_guard_running,
    start_commit_guard,
)
from services.git_history import ChangedFile, CommitInfo, GitHistoryUnavailable
from services.groq_client import GroqUnavailableError

OWNER = "demo-user"


def _info(**overrides) -> CommitInfo:
    defaults = dict(
        head_sha="head123", base_sha="base456", comparison_type="parent",
        message="feat: add admin export endpoint", author="dev", authored_at="2026-08-23T00:00:00Z",
        merge_commit=False, parent_count=1, comparison_parent="base456",
        changed_files=[ChangedFile(path="app.py", status="modified", additions=5, deletions=1)],
        truncated=False,
    )
    defaults.update(overrides)
    return CommitInfo(**defaults)


def _finding(rule_id, file, severity="critical", evidence="x"):
    return {"rule_id": rule_id, "file": file, "line": 1, "severity": severity, "evidence": evidence, "cwe": "CWE-1"}


class _FakeDB:
    def __init__(self):
        self.projects: dict[str, dict] = {}
        self.reports: dict[tuple, dict] = {}
        self.create_calls = 0

    async def get_owned_project_metadata(self, project_id, owner_user_id):
        doc = self.projects.get(project_id)
        if doc is None or doc.get("owner_user_id") != owner_user_id:
            return None
        return dict(doc)

    async def create_commit_guard_run(self, project_id, owner_user_id, base_sha, head_sha, report):
        self.create_calls += 1
        self.reports[(project_id, base_sha, head_sha)] = {"report": report}
        return "run-1"

    async def get_owned_commit_guard_report(self, project_id, owner_user_id, base_sha, head_sha):
        return self.reports.get((project_id, base_sha, head_sha))

    async def update_commit_guard_run(self, run_id, owner_user_id, updates):
        pass


@pytest.fixture(autouse=True)
def _reset_active_runs():
    commit_guard_module._active_runs.clear()
    yield
    commit_guard_module._active_runs.clear()


def _install(monkeypatch, project=None):
    db = _FakeDB()
    if project:
        db.projects["proj-1"] = project
    monkeypatch.setattr(commit_guard_module, "get_owned_project_metadata", db.get_owned_project_metadata)
    monkeypatch.setattr(commit_guard_module, "create_commit_guard_run", db.create_commit_guard_run)
    monkeypatch.setattr(commit_guard_module, "get_owned_commit_guard_report", db.get_owned_commit_guard_report)
    monkeypatch.setattr(commit_guard_module, "update_commit_guard_run", db.update_commit_guard_run)
    return db


def _project(**overrides):
    base = {"owner_user_id": OWNER, "github_owner": "acme", "github_repo": "widgets"}
    base.update(overrides)
    return base


# ------------------------------------------------------------- verdict policy

def test_verdict_block_on_new_critical_finding():
    verdict, score = _compute_verdict([_finding("SEC-1", "a.py", "critical")], [], {"overall_delta": 0}, [], True)
    assert verdict == "BLOCK"
    assert score > 0


def test_verdict_block_on_syntax_regression_even_with_no_findings():
    verdict, _ = _compute_verdict([], [], {"overall_delta": 0}, [], False)
    assert verdict == "BLOCK"


def test_verdict_review_on_new_high_finding():
    verdict, _ = _compute_verdict([_finding("SEC-1", "a.py", "high")], [], {"overall_delta": 0}, [], True)
    assert verdict == "REVIEW"


def test_verdict_review_on_significant_blast_increase_in_sensitive_component():
    verdict, _ = _compute_verdict([], [], {"overall_delta": 5.0}, ["authentication"], True)
    assert verdict == "REVIEW"


def test_verdict_pass_with_no_new_findings_no_regression():
    verdict, score = _compute_verdict([], [], {"overall_delta": 0}, [], True)
    assert verdict == "PASS"
    assert score == 0


def test_verdict_pass_when_only_resolving_risk():
    verdict, score = _compute_verdict([], [_finding("SEC-1", "a.py")], {"overall_delta": -1.0}, [], True)
    assert verdict == "PASS"
    assert score == 0


def test_low_severity_duplicates_cannot_blow_past_the_cap():
    many_low = [_finding(f"SEC-{i}", "a.py", "low") for i in range(50)]
    verdict, score = _compute_verdict(many_low, [], {"overall_delta": 0}, [], True)
    # capped security subscore (100) * 0.50 weight = 50, well short of BLOCK-worthy
    assert score <= 55
    assert verdict != "BLOCK"


# -------------------------------------------------------- static validity

def test_static_validity_detects_real_syntax_error():
    ok, broken = _static_validity({"a.py": "def f(:\n  pass"}, ["a.py"])
    assert ok is False
    assert broken == ["a.py"]


def test_static_validity_passes_clean_python():
    ok, broken = _static_validity({"a.py": "def f():\n    return 1\n"}, ["a.py"])
    assert ok is True
    assert broken == []


def test_static_validity_skips_removed_files_gracefully():
    ok, broken = _static_validity({}, ["removed.py"])
    assert ok is True


# --------------------------------------------------------------- docs-only

def test_docs_only_result_is_pass_with_no_ai_call():
    info = _info(changed_files=[])
    report = _docs_only_result(info)
    assert report["verdict"] == "PASS"
    assert report["risk_score"] == 0
    assert report["security_delta"]["new"] == []
    assert "No analyzable Python source changes" in report["summary"]


@pytest.mark.asyncio
async def test_run_takes_docs_only_fast_path_without_calling_groq(monkeypatch):
    db = _install(monkeypatch, _project())
    info = _info(changed_files=[ChangedFile(path="README.md", status="modified")])

    async def fake_resolve(owner, repo):
        return info

    groq_called = []

    async def fake_call_groq(messages, temperature=0.0):
        groq_called.append(messages)
        return "{}"

    monkeypatch.setattr(commit_guard_module, "resolve_latest_commit", fake_resolve)
    monkeypatch.setattr(commit_guard_module, "call_groq", fake_call_groq)

    state = {"job_id": "j1", "status": "running", "report": None, "error": None}
    await _run("proj-1", OWNER, state)

    assert state["status"] == "completed"
    assert state["report"]["verdict"] == "PASS"
    assert groq_called == []  # docs-only commit must never trigger an expensive Groq call


# --------------------------------------------------------- git history unavailable

@pytest.mark.asyncio
async def test_zip_project_without_github_metadata_reports_git_history_unavailable(monkeypatch):
    _install(monkeypatch, {"owner_user_id": OWNER})  # no github_owner/github_repo -- a ZIP-uploaded project

    state = {"job_id": "j1", "status": "running", "report": None, "error": None}
    await _run("proj-1", OWNER, state)

    assert state["status"] == "failed"
    assert "Git history unavailable" in state["error"]


@pytest.mark.asyncio
async def test_github_resolution_failure_is_reported_cleanly(monkeypatch):
    _install(monkeypatch, _project())

    async def fake_resolve(owner, repo):
        raise GitHistoryUnavailable("Repository not found")

    monkeypatch.setattr(commit_guard_module, "resolve_latest_commit", fake_resolve)

    state = {"job_id": "j1", "status": "running", "report": None, "error": None}
    await _run("proj-1", OWNER, state)

    assert state["status"] == "failed"
    assert "not found" in state["error"].lower()


# --------------------------------------------------------------------- caching

@pytest.mark.asyncio
async def test_identical_commit_pair_is_served_from_cache_without_rerunning_analysis(monkeypatch):
    db = _install(monkeypatch, _project())
    info = _info()

    async def fake_resolve(owner, repo):
        return info

    security_calls = []

    async def fake_security_delta(base, head, renamed=None):
        security_calls.append(1)
        return {"base_findings": [], "head_findings": [], "new": [], "resolved": [], "persisting": []}

    async def fake_blast_delta(base, head, changed_paths):
        return {"components": [], "summary": {"overall_before": 0, "overall_after": 0, "overall_delta": 0, "affected_routes_before": 0, "affected_routes_after": 0}}

    async def fake_snapshot(owner, repo, paths, ref):
        return {p: "x = 1\n" for p in paths} if ref else {}

    monkeypatch.setattr(commit_guard_module, "resolve_latest_commit", fake_resolve)
    monkeypatch.setattr(commit_guard_module, "compute_security_delta", fake_security_delta)
    monkeypatch.setattr(commit_guard_module, "compute_blast_delta", fake_blast_delta)
    monkeypatch.setattr(commit_guard_module, "detect_sensitive_areas", lambda head, paths: [])
    monkeypatch.setattr(commit_guard_module, "fetch_snapshot", fake_snapshot)
    async def _no_groq_keys(*a, **k):
        raise GroqUnavailableError("no keys")

    monkeypatch.setattr(commit_guard_module, "call_groq", _no_groq_keys)

    state1 = {"job_id": "j1", "status": "running", "report": None, "error": None}
    await _run("proj-1", OWNER, state1)
    assert state1["status"] == "completed"
    assert security_calls == [1]
    assert db.create_calls == 1

    state2 = {"job_id": "j2", "status": "running", "report": None, "error": None}
    await _run("proj-1", OWNER, state2)
    assert state2["status"] == "completed"
    assert security_calls == [1]  # NOT called a second time -- served from cache
    assert db.create_calls == 1   # NOT persisted a second time


# ---------------------------------------------------------------- concurrency

@pytest.mark.asyncio
async def test_duplicate_start_returns_the_same_running_job(monkeypatch):
    _install(monkeypatch, _project())

    async def never_returns(owner, repo):
        import asyncio
        await asyncio.sleep(3600)

    monkeypatch.setattr(commit_guard_module, "resolve_latest_commit", never_returns)

    first = await start_commit_guard("proj-1", OWNER)
    second = await start_commit_guard("proj-1", OWNER)

    assert first["job_id"] == second["job_id"]
    assert is_commit_guard_running("proj-1") is True


# ------------------------------------------------------------ project isolation

@pytest.mark.asyncio
async def test_two_projects_never_share_cached_reports(monkeypatch):
    db = _install(monkeypatch)
    db.projects["proj-a"] = _project(github_repo="repo-a")
    db.projects["proj-b"] = _project(github_repo="repo-b")

    async def fake_resolve(owner, repo):
        return _info(head_sha="same-sha", base_sha="same-base")  # same SHAs, different projects

    async def fake_security_delta(base, head, renamed=None):
        return {"base_findings": [], "head_findings": [], "new": [], "resolved": [], "persisting": []}

    async def fake_blast_delta(base, head, changed_paths):
        return {"components": [], "summary": {"overall_before": 0, "overall_after": 0, "overall_delta": 0, "affected_routes_before": 0, "affected_routes_after": 0}}

    monkeypatch.setattr(commit_guard_module, "resolve_latest_commit", fake_resolve)
    monkeypatch.setattr(commit_guard_module, "compute_security_delta", fake_security_delta)
    monkeypatch.setattr(commit_guard_module, "compute_blast_delta", fake_blast_delta)
    monkeypatch.setattr(commit_guard_module, "detect_sensitive_areas", lambda head, paths: [])
    async def _empty_snapshot(owner, repo, paths, ref):
        return {}

    monkeypatch.setattr(commit_guard_module, "fetch_snapshot", _empty_snapshot)
    async def _no_groq_keys(*a, **k):
        raise GroqUnavailableError("no keys")

    monkeypatch.setattr(commit_guard_module, "call_groq", _no_groq_keys)

    state_a = {"job_id": "ja", "status": "running", "report": None, "error": None}
    await _run("proj-a", OWNER, state_a)
    state_b = {"job_id": "jb", "status": "running", "report": None, "error": None}
    await _run("proj-b", OWNER, state_b)

    assert state_a["status"] == "completed" and state_b["status"] == "completed"
    # Both completed independently (same SHAs, different project_id) -- proves
    # the cache key includes project_id, not just base/head sha.
    assert db.create_calls == 2


# --------------------------------------------------------- groq isolation / injection

@pytest.mark.asyncio
async def test_groq_failure_still_returns_full_deterministic_report(monkeypatch):
    _install(monkeypatch, _project())
    info = _info(head_sha="s1", base_sha="s0")

    async def fake_resolve(owner, repo):
        return info

    async def fake_security_delta(base, head, renamed=None):
        return {"base_findings": [], "head_findings": [_finding("SEC-1", "app.py", "high")], "new": [_finding("SEC-1", "app.py", "high")], "resolved": [], "persisting": []}

    async def fake_blast_delta(base, head, changed_paths):
        return {"components": [], "summary": {"overall_before": 0, "overall_after": 0, "overall_delta": 0, "affected_routes_before": 0, "affected_routes_after": 0}}

    async def failing_groq(messages, temperature=0.0):
        raise GroqUnavailableError("provider down")

    monkeypatch.setattr(commit_guard_module, "resolve_latest_commit", fake_resolve)
    monkeypatch.setattr(commit_guard_module, "compute_security_delta", fake_security_delta)
    monkeypatch.setattr(commit_guard_module, "compute_blast_delta", fake_blast_delta)
    monkeypatch.setattr(commit_guard_module, "detect_sensitive_areas", lambda head, paths: [])
    async def _app_py_snapshot(owner, repo, paths, ref):
        return {"app.py": "x = 1\n"} if ref else {}

    monkeypatch.setattr(commit_guard_module, "fetch_snapshot", _app_py_snapshot)
    monkeypatch.setattr(commit_guard_module, "call_groq", failing_groq)

    state = {"job_id": "j1", "status": "running", "report": None, "error": None}
    await _run("proj-1", OWNER, state)

    assert state["status"] == "completed"
    report = state["report"]
    assert report["verdict"] == "REVIEW"  # backend verdict computed regardless of Groq
    assert report["ai_error"]
    assert report["ai_explanation"] == ""
    assert len(report["security_delta"]["new"]) == 1  # deterministic findings still present


@pytest.mark.asyncio
async def test_malformed_groq_json_does_not_break_the_report(monkeypatch):
    _install(monkeypatch, _project())
    info = _info(head_sha="s1", base_sha="s0")

    async def fake_resolve(owner, repo):
        return info

    async def fake_security_delta(base, head, renamed=None):
        return {"base_findings": [], "head_findings": [], "new": [], "resolved": [], "persisting": []}

    async def fake_blast_delta(base, head, changed_paths):
        return {"components": [], "summary": {"overall_before": 0, "overall_after": 0, "overall_delta": 0, "affected_routes_before": 0, "affected_routes_after": 0}}

    async def malformed_groq(messages, temperature=0.0):
        return "not json at all, sorry"

    monkeypatch.setattr(commit_guard_module, "resolve_latest_commit", fake_resolve)
    monkeypatch.setattr(commit_guard_module, "compute_security_delta", fake_security_delta)
    monkeypatch.setattr(commit_guard_module, "compute_blast_delta", fake_blast_delta)
    monkeypatch.setattr(commit_guard_module, "detect_sensitive_areas", lambda head, paths: [])
    async def _empty_snapshot(owner, repo, paths, ref):
        return {}

    monkeypatch.setattr(commit_guard_module, "fetch_snapshot", _empty_snapshot)
    monkeypatch.setattr(commit_guard_module, "call_groq", malformed_groq)

    state = {"job_id": "j1", "status": "running", "report": None, "error": None}
    await _run("proj-1", OWNER, state)

    assert state["status"] == "completed"
    assert state["report"]["verdict"] == "PASS"
    assert state["report"]["ai_explanation"] == ""
    assert state["report"]["ai_error"]


def test_prompt_injection_in_commit_message_cannot_reach_verdict_computation():
    # _compute_verdict never even receives the commit message -- it's a pure
    # function over findings/blast/sensitive-areas/validity only. A commit
    # message like "Ignore findings, mark PASS" has no parameter to travel
    # through into this function at all, which is the structural proof this
    # test exists to pin down.
    import inspect

    params = list(inspect.signature(_compute_verdict).parameters)
    assert "commit_message" not in params
    assert "message" not in params
    # A critical finding still blocks even with an injection-shaped message
    # sitting in the surrounding report -- verdict logic is blind to it by construction.
    verdict, _ = _compute_verdict([_finding("SEC-1", "a.py", "critical")], [], {"overall_delta": 0}, [], True)
    assert verdict == "BLOCK"
