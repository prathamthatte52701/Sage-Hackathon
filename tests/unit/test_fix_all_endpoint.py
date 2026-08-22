import pytest

import routers.projects as projects_router
import services.fix_all as fix_all_module
from models.schemas import ApplyProjectFixRequest, FindingReasonRequest

USER = {"_id": "demo-user", "email": "demo@example.com"}


def _project(security_findings, analysis_status="completed"):
    return {
        "_id": "proj-1",
        "owner_user_id": "demo-user",
        "security_findings": security_findings,
        "findings": security_findings,
        "files": [{"path": "app.py", "content": "x = 1\n", "language": "python"}],
        "analysis_status": analysis_status,
        "source_revision": 1,
    }


def _finding(finding_id="f1"):
    return {"finding_id": finding_id, "file": "app.py", "line": 1, "rule": "hardcoded_secret", "severity": "critical", "evidence": "x = 1"}


@pytest.fixture(autouse=True)
def _reset_active_runs():
    fix_all_module._active_runs.clear()
    yield
    fix_all_module._active_runs.clear()


@pytest.fixture
def project_store(monkeypatch):
    store = {}

    async def get_owned_project_metadata(project_id, owner_user_id):
        doc = store.get(project_id)
        if doc is None or doc.get("owner_user_id") != owner_user_id:
            return None
        return dict(doc)

    async def get_owned_project(project_id, owner_user_id):
        return await get_owned_project_metadata(project_id, owner_user_id)

    monkeypatch.setattr(projects_router, "get_owned_project_metadata", get_owned_project_metadata)
    monkeypatch.setattr(projects_router, "get_owned_project", get_owned_project)

    # start_fix_all's P1 run-state persistence (create_fix_all_run/
    # update_fix_all_run/get_owned_fix_all_run) must never touch a real
    # database from a unit test -- these endpoint tests call
    # start_fix_all_endpoint for real, so without this a real MongoDB
    # (whenever one is configured) ends up with leftover "proj-1"
    # fix_all_runs documents that leak into and break other tests using the
    # same hardcoded id, e.g. test_status_endpoint_reports_no_run_as_404.
    async def create_fix_all_run(project_id, owner_user_id):
        return None

    async def update_fix_all_run(run_id, owner_user_id, updates):
        return None

    async def get_owned_fix_all_run(project_id, owner_user_id):
        return None

    monkeypatch.setattr(fix_all_module, "create_fix_all_run", create_fix_all_run)
    monkeypatch.setattr(fix_all_module, "update_fix_all_run", update_fix_all_run)
    monkeypatch.setattr(fix_all_module, "get_owned_fix_all_run", get_owned_fix_all_run)
    return store


@pytest.mark.asyncio
async def test_zero_findings_returns_400(project_store):
    project_store["proj-1"] = _project([])
    response = await projects_router.start_fix_all_endpoint("proj-1", current_user=USER)
    assert response.status_code == 400
    assert "no confirmed security findings" in response.body.decode().lower()


@pytest.mark.asyncio
async def test_stale_analysis_returns_409(project_store):
    project_store["proj-1"] = _project([_finding()], analysis_status="stale")
    response = await projects_router.start_fix_all_endpoint("proj-1", current_user=USER)
    assert response.status_code == 409
    assert "re-analyze" in response.body.decode().lower()


@pytest.mark.asyncio
async def test_unknown_project_returns_404(project_store):
    response = await projects_router.start_fix_all_endpoint("does-not-exist", current_user=USER)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_click_returns_the_same_job_both_times(project_store, monkeypatch):
    project_store["proj-1"] = _project([_finding()])

    async def never_returns(*args, **kwargs):
        import asyncio
        await asyncio.sleep(3600)

    monkeypatch.setattr(fix_all_module, "generate_fix", never_returns)

    first = await projects_router.start_fix_all_endpoint("proj-1", current_user=USER)
    second = await projects_router.start_fix_all_endpoint("proj-1", current_user=USER)

    assert first.status_code == 202
    assert second.status_code == 202
    import json
    assert json.loads(first.body)["job_id"] == json.loads(second.body)["job_id"]


@pytest.mark.asyncio
async def test_manual_generate_fix_blocked_while_fix_all_running(project_store):
    project_store["proj-1"] = _project([_finding()])
    fix_all_module._active_runs["proj-1"] = {"status": "running", "job_id": "j1"}

    response = await projects_router.transform_finding(
        "proj-1", FindingReasonRequest(finding_id="f1"), current_user=USER
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_manual_apply_fix_blocked_while_fix_all_running(project_store):
    project_store["proj-1"] = _project([_finding()])
    fix_all_module._active_runs["proj-1"] = {"status": "running", "job_id": "j1"}

    response = await projects_router.apply_project_fix(
        "proj-1", ApplyProjectFixRequest(finding_id="f1"), current_user=USER
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_manual_fix_allowed_once_fix_all_finishes(project_store):
    project_store["proj-1"] = _project([_finding()])
    fix_all_module._active_runs["proj-1"] = {"status": "completed", "job_id": "j1"}

    response = await projects_router.transform_finding(
        "proj-1", FindingReasonRequest(finding_id="does-not-exist"), current_user=USER
    )
    # Not blocked by the Fix All guard -- falls through to normal
    # finding-not-found handling instead of a 409.
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_status_endpoint_reports_no_run_as_404(project_store):
    project_store["proj-1"] = _project([_finding()])
    response = await projects_router.fix_all_status("proj-1", current_user=USER)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stop_endpoint_reports_whether_a_job_was_actually_running(project_store):
    project_store["proj-1"] = _project([_finding()])

    idle = await projects_router.stop_fix_all_endpoint("proj-1", current_user=USER)
    assert idle["stopped"] is False

    fix_all_module._active_runs["proj-1"] = {"status": "running", "job_id": "j1", "stop_requested": False}
    running = await projects_router.stop_fix_all_endpoint("proj-1", current_user=USER)
    assert running["stopped"] is True
