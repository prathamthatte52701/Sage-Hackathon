import pytest

import services.pr_guard as pr_guard_module
from services.git_history import ChangedFile, GitHistoryUnavailable, PullRequestInfo
from services.groq_client import GroqUnavailableError
from services.pr_guard import _compute_verdict, _run, get_pr_guard_status, start_pr_guard


OWNER = "demo-user"
PROJECT_ID = "proj-1"


def _pr_info(**overrides) -> PullRequestInfo:
    defaults = dict(
        number=7,
        title="Add admin export",
        body="",
        state="open",
        merged=False,
        author="dev",
        base_branch="main",
        head_branch="feature/admin-export",
        base_sha="base123",
        head_sha="head456",
        merge_base_sha="merge789",
        commit_count=2,
        changed_file_count=1,
        additions=5,
        deletions=1,
        changed_files=[ChangedFile(path="app.py", status="modified", additions=5, deletions=1)],
        truncated=False,
    )
    defaults.update(overrides)
    return PullRequestInfo(**defaults)


def _finding(rule_id="SEC-1", severity="critical"):
    return {"rule_id": rule_id, "file": "app.py", "line": 1, "severity": severity, "evidence": "x"}


class _FakeDB:
    def __init__(self, project=None):
        self.project = project or {"owner_user_id": OWNER, "github_owner": "acme", "github_repo": "widgets"}
        self.cached = None
        self.created = []
        self.updates = {}

    async def get_owned_project_metadata(self, project_id, owner_user_id):
        if project_id != PROJECT_ID or owner_user_id != OWNER:
            return None
        return dict(self.project) if self.project is not None else None

    async def create_pr_guard_run(self, project_id, owner_user_id, pr_number, state):
        self.created.append((project_id, owner_user_id, pr_number, state))
        return "persisted-run-1"

    async def update_pr_guard_run(self, run_id, owner_user_id, updates):
        self.updates[run_id] = updates

    async def get_owned_pr_guard_run(self, project_id, owner_user_id, run_id):
        return self.updates.get(run_id)

    async def get_owned_pr_guard_cached_report(self, project_id, owner_user_id, pr_number, merge_base_sha, head_sha):
        return self.cached


@pytest.fixture(autouse=True)
def _reset_active_runs():
    pr_guard_module._active_runs.clear()
    pr_guard_module._active_by_project_pr.clear()
    yield
    pr_guard_module._active_runs.clear()
    pr_guard_module._active_by_project_pr.clear()


def _install_db(monkeypatch, project=None):
    db = _FakeDB(project)
    monkeypatch.setattr(pr_guard_module, "get_owned_project_metadata", db.get_owned_project_metadata)
    monkeypatch.setattr(pr_guard_module, "create_pr_guard_run", db.create_pr_guard_run)
    monkeypatch.setattr(pr_guard_module, "update_pr_guard_run", db.update_pr_guard_run)
    monkeypatch.setattr(pr_guard_module, "get_owned_pr_guard_run", db.get_owned_pr_guard_run)
    monkeypatch.setattr(pr_guard_module, "get_owned_pr_guard_cached_report", db.get_owned_pr_guard_cached_report)
    return db


def test_verdict_blocks_critical_or_syntax_regression():
    verdict, _ = _compute_verdict([_finding(severity="critical")], {"overall_delta": 0}, [], {"direction": "UNCHANGED", "dimensions": {}}, True)
    assert verdict == "BLOCK"

    verdict, _ = _compute_verdict([], {"overall_delta": 0}, [], {"direction": "UNCHANGED", "dimensions": {}}, False)
    assert verdict == "BLOCK"


def test_verdict_reviews_significant_quality_degradation():
    quality_delta = {
        "direction": "DEGRADED",
        "dimensions": {
            "reliability": {"delta": -2.0},
            "maintainability": {"delta": -1.0},
        },
    }
    verdict, score = _compute_verdict([], {"overall_delta": 0}, [], quality_delta, True)

    assert verdict == "REVIEW"
    assert score > 0


@pytest.mark.asyncio
async def test_docs_only_pr_completes_without_snapshots_or_groq(monkeypatch):
    _install_db(monkeypatch)
    info = _pr_info(changed_files=[ChangedFile(path="README.md", status="modified")])

    async def fake_resolve(owner, repo, number):
        return info

    async def fail_fetch(*args, **kwargs):
        raise AssertionError("docs-only PR must not fetch file snapshots")

    async def fail_groq(*args, **kwargs):
        raise AssertionError("docs-only PR must not call Groq")

    monkeypatch.setattr(pr_guard_module, "resolve_pull_request", fake_resolve)
    monkeypatch.setattr(pr_guard_module, "fetch_snapshot", fail_fetch)
    monkeypatch.setattr(pr_guard_module, "call_groq", fail_groq)

    state = {"run_id": "run-1", "job_id": "run-1", "project_id": PROJECT_ID, "owner_user_id": OWNER, "pull_request_number": 7, "status": "queued", "stage": "queued", "report": None, "error": None}
    await _run(PROJECT_ID, OWNER, 7, state)

    assert state["status"] == "complete"
    assert state["report"]["verdict"] == "PASS"
    assert state["report"]["security_delta"]["new"] == []
    assert "no analyzable python source" in state["report"]["summary"].lower()


@pytest.mark.asyncio
async def test_cached_pr_report_skips_reanalysis(monkeypatch):
    db = _install_db(monkeypatch)
    db.cached = {"report": {"verdict": "PASS", "cached": True}}

    async def fake_resolve(owner, repo, number):
        return _pr_info()

    async def fail_security(*args, **kwargs):
        raise AssertionError("cached PR report must not recompute security delta")

    monkeypatch.setattr(pr_guard_module, "resolve_pull_request", fake_resolve)
    monkeypatch.setattr(pr_guard_module, "compute_security_delta", fail_security)

    state = {"run_id": "run-1", "job_id": "run-1", "project_id": PROJECT_ID, "owner_user_id": OWNER, "pull_request_number": 7, "status": "queued", "stage": "queued", "report": None, "error": None}
    await _run(PROJECT_ID, OWNER, 7, state)

    assert state["status"] == "complete"
    assert state["report"] == {"verdict": "PASS", "cached": True}


@pytest.mark.asyncio
async def test_stale_pr_head_is_marked_after_analysis(monkeypatch):
    _install_db(monkeypatch)

    async def fake_resolve(owner, repo, number):
        return _pr_info()

    async def fake_fetch(owner, repo, paths, ref):
        if ref == "head456":
            return {"app.py": "def ok():\n    return 1\n"}
        return {"app.py": "def ok():\n    return 0\n"}

    async def fake_security_delta(base, head, renamed=None):
        return {"base_findings": [], "head_findings": [], "new": [], "resolved": [], "persisting": []}

    async def fake_blast_delta(base, head, changed_paths):
        return {"components": [], "summary": {"overall_before": 0, "overall_after": 0, "overall_delta": 0, "affected_routes_before": 0, "affected_routes_after": 0}}

    async def no_groq_keys(*args, **kwargs):
        raise GroqUnavailableError("no keys")

    monkeypatch.setattr(pr_guard_module, "resolve_pull_request", fake_resolve)
    monkeypatch.setattr(pr_guard_module, "fetch_snapshot", fake_fetch)
    monkeypatch.setattr(pr_guard_module, "compute_security_delta", fake_security_delta)
    monkeypatch.setattr(pr_guard_module, "compute_blast_delta", fake_blast_delta)
    monkeypatch.setattr(pr_guard_module, "detect_sensitive_areas", lambda head, paths: [])
    monkeypatch.setattr(pr_guard_module, "call_groq", no_groq_keys)
    async def fake_head_sha(owner, repo, number):
        return "newhead999"

    monkeypatch.setattr(pr_guard_module, "resolve_pull_request_head_sha", fake_head_sha)

    state = {"run_id": "run-1", "job_id": "run-1", "project_id": PROJECT_ID, "owner_user_id": OWNER, "pull_request_number": 7, "status": "queued", "stage": "queued", "report": None, "error": None}
    await _run(PROJECT_ID, OWNER, 7, state)

    assert state["status"] == "complete"
    assert state["report"]["stale"] is True
    assert state["report"]["current_head_sha"] == "newhead999"
    assert state["report"]["verdict"] == "PASS"


@pytest.mark.asyncio
async def test_duplicate_start_returns_same_running_pr_job(monkeypatch):
    _install_db(monkeypatch)

    def fake_create_task(coro, name=None):
        coro.close()
        return object()

    monkeypatch.setattr(pr_guard_module.asyncio, "create_task", fake_create_task)

    first = await start_pr_guard(PROJECT_ID, OWNER, 7)
    second = await start_pr_guard(PROJECT_ID, OWNER, 7)

    assert first["run_id"] == second["run_id"]
    assert len(pr_guard_module._active_runs) == 1


@pytest.mark.asyncio
async def test_status_recovers_interrupted_persisted_run(monkeypatch):
    db = _install_db(monkeypatch)
    db.updates["run-1"] = {"run_id": "run-1", "project_id": PROJECT_ID, "status": "queued", "stage": "building_diff"}

    state = await get_pr_guard_status(PROJECT_ID, OWNER, "run-1")

    assert state["status"] == "failed"
    assert state["stage"] == "failed"
    assert "interrupted" in state["error"].lower()
