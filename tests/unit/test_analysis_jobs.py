import asyncio

import pytest

from services import analysis_jobs


@pytest.mark.asyncio
async def test_duplicate_enqueue_returns_one_inflight_job(monkeypatch):
    jobs = {}
    created = []
    completed = asyncio.Event()

    async def create(project_id, owner_user_id):
        job_id = f"job-{len(created) + 1}"
        created.append(job_id)
        jobs[job_id] = {"_id": job_id, "project_id": project_id, "owner_user_id": owner_user_id, "status": "queued"}
        return job_id

    async def get(job_id, owner_user_id):
        job = jobs.get(job_id)
        return dict(job) if job and job["owner_user_id"] == owner_user_id else None

    async def update(job_id, owner_user_id, updates):
        jobs[job_id].update(updates)

    async def work(_job_id):
        await completed.wait()
        return {"partial": False}

    monkeypatch.setattr(analysis_jobs, "create_analysis_job", create)
    monkeypatch.setattr(analysis_jobs, "get_owned_analysis_job", get)
    monkeypatch.setattr(analysis_jobs, "update_analysis_job", update)
    analysis_jobs._running_jobs.clear()

    first, first_created = await analysis_jobs.enqueue_analysis("project-1", "user-1", work)
    second, second_created = await analysis_jobs.enqueue_analysis("project-1", "user-1", work)

    assert first_created is True
    assert second_created is False
    assert first["_id"] == second["_id"]
    assert created == ["job-1"]

    completed.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert jobs["job-1"]["status"] == "completed"
