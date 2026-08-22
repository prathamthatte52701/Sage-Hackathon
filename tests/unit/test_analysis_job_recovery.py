from datetime import datetime, timedelta, timezone

import pytest

import services.analysis_jobs as jobs_module
from services.analysis_jobs import get_analysis_job_with_recovery

OWNER = "demo-user"


class _FakeJobsDB:
    def __init__(self):
        self.jobs: dict[str, dict] = {}

    async def get_owned_analysis_job(self, job_id, owner_user_id):
        job = self.jobs.get(job_id)
        if job is None or job.get("owner_user_id") != owner_user_id:
            return None
        return dict(job)

    async def update_analysis_job(self, job_id, owner_user_id, updates):
        job = self.jobs.get(job_id)
        if job is None or job.get("owner_user_id") != owner_user_id:
            return
        job.update(updates)


@pytest.fixture(autouse=True)
def _reset_registry():
    jobs_module._running_jobs.clear()
    yield
    jobs_module._running_jobs.clear()


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeJobsDB()
    monkeypatch.setattr(jobs_module, "get_owned_analysis_job", db.get_owned_analysis_job)
    monkeypatch.setattr(jobs_module, "update_analysis_job", db.update_analysis_job)
    return db


@pytest.mark.asyncio
async def test_job_owned_by_a_live_task_is_left_alone(fake_db):
    fake_db.jobs["job-1"] = {
        "owner_user_id": OWNER, "project_id": "proj-1", "status": "running",
        "started_at": datetime.now(timezone.utc) - timedelta(minutes=5),
    }
    jobs_module._running_jobs[(OWNER, "proj-1")] = "job-1"

    job = await get_analysis_job_with_recovery("job-1", OWNER)

    assert job["status"] == "running"


@pytest.mark.asyncio
async def test_recently_started_job_is_not_flagged_within_grace_period(fake_db):
    fake_db.jobs["job-1"] = {
        "owner_user_id": OWNER, "project_id": "proj-1", "status": "running",
        "started_at": datetime.now(timezone.utc),
    }
    # No entry in _running_jobs -- simulates the tiny window between
    # create_analysis_job() and the registry write.

    job = await get_analysis_job_with_recovery("job-1", OWNER)

    assert job["status"] == "running"


@pytest.mark.asyncio
async def test_abandoned_running_job_past_grace_period_is_marked_interrupted(fake_db):
    fake_db.jobs["job-1"] = {
        "owner_user_id": OWNER, "project_id": "proj-1", "status": "running",
        "started_at": datetime.now(timezone.utc) - timedelta(minutes=10),
    }
    # No entry in _running_jobs -- this process (e.g. after a restart) has
    # no live task for this job, and it's well past the grace period.

    job = await get_analysis_job_with_recovery("job-1", OWNER)

    assert job["status"] == "failed"
    assert job["error"] == "interrupted"
    assert "restarted" in fake_db.jobs["job-1"]["result"]["error"].lower()


@pytest.mark.asyncio
async def test_abandoned_queued_job_is_also_recovered(fake_db):
    fake_db.jobs["job-1"] = {
        "owner_user_id": OWNER, "project_id": "proj-1", "status": "queued",
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=10),
    }

    job = await get_analysis_job_with_recovery("job-1", OWNER)

    assert job["status"] == "failed"


@pytest.mark.asyncio
async def test_already_terminal_job_is_returned_unchanged(fake_db):
    fake_db.jobs["job-1"] = {"owner_user_id": OWNER, "project_id": "proj-1", "status": "completed"}

    job = await get_analysis_job_with_recovery("job-1", OWNER)

    assert job["status"] == "completed"


@pytest.mark.asyncio
async def test_unknown_job_returns_none(fake_db):
    assert await get_analysis_job_with_recovery("no-such-job", OWNER) is None
