import pytest

from services import automation


OWNER = "demo-user"
PROJECT_ID = "proj-1"


@pytest.fixture(autouse=True)
def clean_runs():
    automation._active_runs.clear()
    yield
    automation._active_runs.clear()


def _state():
    return automation._new_state(PROJECT_ID, OWNER, "automation-test")


@pytest.mark.asyncio
async def test_automation_completes_without_fix_loop_for_zero_findings(monkeypatch):
    project = {
        "source_revision": 1,
        "analysis_revision": 1,
        "security_findings": [],
        "findings": [],
        "files": [{"path": "app.py", "language": "python", "content": "print('ok')\n"}],
    }

    async def fake_get_project(project_id, owner_user_id):
        assert (project_id, owner_user_id) == (PROJECT_ID, OWNER)
        return project

    async def fake_analysis(project_id, owner_user_id):
        project["security_findings"] = []
        project["findings"] = []
        return {"finding_count": 0}

    async def fake_hacker(project):
        return {"attack_surfaces": [], "risk_paths": [], "top_targets": []}

    async def fake_brutal(project):
        return {"overall_score": 8.2, "verdict": "READY WITH HARDENING"}

    async def fake_blast(project):
        return {"summary": {"components_analyzed": 1, "high_impact_components": 0}, "components": []}

    from routers import projects

    monkeypatch.setattr(automation, "get_owned_project_metadata", fake_get_project)
    monkeypatch.setattr(projects, "_run_project_analysis", fake_analysis)
    monkeypatch.setattr(automation, "run_hacker_lens", fake_hacker)
    monkeypatch.setattr(automation, "run_brutal_audit", fake_brutal)
    monkeypatch.setattr(automation, "build_blast_radius", fake_blast)

    state = _state()
    await automation._run_automation(PROJECT_ID, OWNER, state)

    assert state["status"] == "complete"
    assert state["defender"]["status"] == "complete"
    assert state["defender"]["fix_cycles"] == 0
    assert state["final_report"]["defender"]["requires_manual_review"] == 0
    assert state["download"]["fresh"] is True


@pytest.mark.asyncio
async def test_defender_fix_loop_stops_after_two_successful_cycles(monkeypatch):
    project = {"source_revision": 1, "analysis_revision": 1, "security_findings": [{"id": 1}, {"id": 2}], "findings": [{"id": 1}, {"id": 2}]}
    calls = {"fix": 0}

    async def fake_get_project(project_id, owner_user_id):
        return project

    async def fake_analysis(project_id, owner_user_id):
        return {"finding_count": len(project["security_findings"])}

    async def fake_start_fix_all(project_id, owner_user_id):
        calls["fix"] += 1
        if project["security_findings"]:
            project["security_findings"] = project["security_findings"][1:]
            project["findings"] = project["security_findings"]
        return {"status": "completed", "report": {"fixed": 1, "failed": 0}}

    from routers import projects

    monkeypatch.setattr(automation, "get_owned_project_metadata", fake_get_project)
    monkeypatch.setattr(projects, "_run_project_analysis", fake_analysis)
    monkeypatch.setattr(automation, "start_fix_all", fake_start_fix_all)

    state = _state()
    await automation._run_defender(PROJECT_ID, OWNER, state)

    assert calls["fix"] == 2
    assert state["defender"]["status"] == "complete"
    assert state["defender"]["fix_cycles"] == 2
    assert state["defender"]["remaining_findings"] == 0


@pytest.mark.asyncio
async def test_defender_max_cycle_safety_leaves_manual_review(monkeypatch):
    project = {"source_revision": 1, "analysis_revision": 1, "security_findings": [{"id": 1}], "findings": [{"id": 1}]}
    calls = {"fix": 0}

    async def fake_get_project(project_id, owner_user_id):
        return project

    async def fake_analysis(project_id, owner_user_id):
        return {"finding_count": 1}

    async def fake_start_fix_all(project_id, owner_user_id):
        calls["fix"] += 1
        project["source_revision"] += 1
        project["analysis_revision"] += 1
        project["security_findings"] = [{"id": calls["fix"] + 1}]
        project["findings"] = project["security_findings"]
        return {"status": "completed", "report": {"fixed": 0, "failed": 1}}

    from routers import projects

    monkeypatch.setattr(automation, "get_owned_project_metadata", fake_get_project)
    monkeypatch.setattr(projects, "_run_project_analysis", fake_analysis)
    monkeypatch.setattr(automation, "start_fix_all", fake_start_fix_all)

    state = _state()
    await automation._run_defender(PROJECT_ID, OWNER, state)

    assert calls["fix"] == automation.MAX_AUTO_FIX_CYCLES
    assert state["defender"]["status"] == "complete"
    assert state["defender"]["manual_review_required"] is True
    assert state["defender"]["remaining_findings"] == 1
    assert len(state["fix_cycles"]) == automation.MAX_AUTO_FIX_CYCLES


@pytest.mark.asyncio
async def test_defender_no_progress_stops_before_max_cycles(monkeypatch):
    finding = {"id": "SEC-1", "file": "app.py", "line": 3, "severity": "high", "evidence": "x"}
    project = {
        "source_revision": 7,
        "analysis_revision": 7,
        "security_findings": [finding],
        "findings": [finding],
    }
    calls = {"fix": 0}

    async def fake_get_project(project_id, owner_user_id):
        return project

    async def fake_analysis(project_id, owner_user_id):
        return {"finding_count": 1}

    async def fake_start_fix_all(project_id, owner_user_id):
        calls["fix"] += 1
        return {"status": "completed", "report": {"attempted": 1, "fixed": 0, "failed": 1, "skipped": 0}}

    from routers import projects

    monkeypatch.setattr(automation, "get_owned_project_metadata", fake_get_project)
    monkeypatch.setattr(projects, "_run_project_analysis", fake_analysis)
    monkeypatch.setattr(automation, "start_fix_all", fake_start_fix_all)

    state = _state()
    await automation._run_defender(PROJECT_ID, OWNER, state)

    assert calls["fix"] == 1
    assert state["defender"]["no_progress"] is True
    assert state["defender"]["manual_review_required"] is True
    assert state["fix_cycles"][0]["status"] == "no_progress"
    assert state["fix_cycles"][0]["source_revision_before"] == 7
    assert state["fix_cycles"][0]["source_revision_after"] == 7


@pytest.mark.asyncio
async def test_defender_cycle_history_tracks_revision_progress(monkeypatch):
    first = {"id": "SEC-1", "file": "app.py", "line": 3, "severity": "high", "evidence": "x"}
    second = {"id": "SEC-2", "file": "app.py", "line": 9, "severity": "medium", "evidence": "y"}
    project = {
        "source_revision": 10,
        "analysis_revision": 10,
        "security_findings": [first, second],
        "findings": [first, second],
    }

    async def fake_get_project(project_id, owner_user_id):
        return project

    async def fake_analysis(project_id, owner_user_id):
        return {"finding_count": len(project["security_findings"])}

    async def fake_start_fix_all(project_id, owner_user_id):
        project["security_findings"] = [second]
        project["findings"] = [second]
        project["source_revision"] = 11
        project["analysis_revision"] = 11
        return {"status": "completed", "report": {"attempted": 2, "fixed": 1, "failed": 0, "skipped": 1}}

    from routers import projects

    monkeypatch.setattr(automation, "get_owned_project_metadata", fake_get_project)
    monkeypatch.setattr(projects, "_run_project_analysis", fake_analysis)
    monkeypatch.setattr(automation, "start_fix_all", fake_start_fix_all)

    state = _state()
    await automation._run_defender(PROJECT_ID, OWNER, state)

    assert state["fix_cycles"][0]["status"] == "complete"
    assert state["fix_cycles"][0]["findings_before"] == 2
    assert state["fix_cycles"][0]["findings_after"] == 1
    assert state["fix_cycles"][0]["source_revision_before"] == 10
    assert state["fix_cycles"][0]["source_revision_after"] == 11


@pytest.mark.asyncio
async def test_defender_pauses_when_initial_analysis_is_stale(monkeypatch):
    project = {"source_revision": 2, "analysis_revision": 1, "security_findings": [{"id": 1}], "findings": [{"id": 1}]}
    calls = {"fix": 0}

    async def fake_get_project(project_id, owner_user_id):
        return project

    async def stale_analysis(project_id, owner_user_id):
        return {"finding_count": 0, "analysis_revision": 1, "partial": True, "stale": True}

    async def fake_start_fix_all(project_id, owner_user_id):
        calls["fix"] += 1
        return {"status": "completed", "report": {"fixed": 1, "failed": 0}}

    from routers import projects

    monkeypatch.setattr(automation, "get_owned_project_metadata", fake_get_project)
    monkeypatch.setattr(projects, "_run_project_analysis", stale_analysis)
    monkeypatch.setattr(automation, "start_fix_all", fake_start_fix_all)

    state = _state()
    with pytest.raises(RuntimeError, match="latest revision"):
        await automation._run_defender(PROJECT_ID, OWNER, state)

    assert calls["fix"] == 0
    assert state["defender"]["status"] == "paused"
    assert state["defender"]["error"] == "Project source changed during Defender analysis."


@pytest.mark.asyncio
async def test_fix_all_verification_failure_pauses_defender():
    state = _state()
    fix_state = {
        "status": "completed",
        "report": {
            "status": "completed_verification_failed",
            "verification_note": "Fixes were applied, but final verification could not complete.",
        },
    }

    with pytest.raises(RuntimeError, match="final verification"):
        await automation._wait_for_fix_all(PROJECT_ID, OWNER, fix_state, state)

    assert state["defender"]["status"] == "paused"
    assert state["defender"]["error"] == "Fixes were applied, but final verification could not complete."


@pytest.mark.asyncio
async def test_hacker_failure_does_not_block_brutal_or_blast(monkeypatch):
    project = {"source_revision": 1, "analysis_revision": 1, "security_findings": [], "findings": []}

    async def fake_get_project(project_id, owner_user_id):
        return project

    async def fake_analysis(project_id, owner_user_id):
        return {"finding_count": 0}

    async def fail_hacker(project):
        raise RuntimeError("groq down")

    async def fake_brutal(project):
        return {"overall_score": 7.5, "verdict": "READY WITH HARDENING"}

    async def fake_blast(project):
        return {"summary": {"components_analyzed": 1, "high_impact_components": 0}, "components": []}

    from routers import projects

    monkeypatch.setattr(automation, "get_owned_project_metadata", fake_get_project)
    monkeypatch.setattr(projects, "_run_project_analysis", fake_analysis)
    monkeypatch.setattr(automation, "run_hacker_lens", fail_hacker)
    monkeypatch.setattr(automation, "run_brutal_audit", fake_brutal)
    monkeypatch.setattr(automation, "build_blast_radius", fake_blast)

    state = _state()
    await automation._run_automation(PROJECT_ID, OWNER, state)

    assert state["status"] == "complete"
    assert state["warnings"] is True
    assert state["hacker"]["status"] == "failed"
    assert state["brutal"]["status"] == "complete"
    assert state["blast_radius"]["status"] == "complete"


@pytest.mark.asyncio
async def test_duplicate_automation_start_returns_existing_run(monkeypatch):
    async def fake_get_project(project_id, owner_user_id):
        return {"security_findings": []}

    async def fake_create_persisted_run(state):
        state["run_id"] = "run-1"

    def fake_create_task(coro, name=None):
        coro.close()
        return object()

    monkeypatch.setattr(automation, "get_owned_project_metadata", fake_get_project)
    monkeypatch.setattr(automation, "_create_persisted_run", fake_create_persisted_run)
    monkeypatch.setattr(automation.asyncio, "create_task", fake_create_task)

    first = await automation.start_automation(PROJECT_ID, OWNER)
    second = await automation.start_automation(PROJECT_ID, OWNER)

    assert first["job_id"] == second["job_id"]
    assert len(automation._active_runs) == 1
