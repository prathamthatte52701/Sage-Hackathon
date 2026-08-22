"""Small in-process analysis job coordinator.

Jobs are persisted in Mongo so status survives an HTTP request, while running
tasks remain process-local by design. That is sufficient for the single-process
demo deployment and makes the limitation explicit rather than pretending this
is a distributed worker queue.
"""

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable

from db.mongo import create_analysis_job, get_owned_analysis_job, update_analysis_job

_running_jobs: dict[tuple[str, str], str] = {}
_guard = asyncio.Lock()


async def enqueue_analysis(
    project_id: str,
    owner_user_id: str,
    work: Callable[[str], Awaitable[dict]],
) -> tuple[dict, bool]:
    """Return an existing in-flight job or create exactly one new job."""
    key = (owner_user_id, project_id)
    async with _guard:
        existing_id = _running_jobs.get(key)
        if existing_id:
            existing = await get_owned_analysis_job(existing_id, owner_user_id)
            if existing and existing.get("status") in {"queued", "running"}:
                return existing, False
            _running_jobs.pop(key, None)

        job_id = await create_analysis_job(project_id, owner_user_id)
        _running_jobs[key] = job_id
        asyncio.create_task(_run_job(job_id, key, work), name=f"analysis:{project_id}")
        job = await get_owned_analysis_job(job_id, owner_user_id)
        return job or {"_id": job_id, "status": "queued"}, True


# If Uvicorn crashes/restarts mid-analysis, Mongo is left holding a job
# doc stuck at status="queued"/"running" forever -- _running_jobs (this
# process's only record of which task actually owns it) is gone, and
# nothing will ever transition that doc again. A brand-new process has an
# empty _running_jobs, so "not in the registry" is an unambiguous signal
# in this single-process deployment, not a heuristic -- the only thing
# that ever clears status is _run_job's own completion handler above. The
# grace period exists only to avoid a false-positive on the couple of
# awaits between create_analysis_job() and the registry write in
# enqueue_analysis() above.
STALE_JOB_GRACE_SECONDS = 30


def _job_age_seconds(job: dict) -> float | None:
    started = job.get("started_at") or job.get("created_at")
    if started is None:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started).total_seconds()


async def get_analysis_job_with_recovery(job_id: str, owner_user_id: str) -> dict | None:
    """Same contract as db.mongo.get_owned_analysis_job, but detects a job
    this process has abandoned (crash/restart while it was in flight) and
    corrects it to "failed" instead of leaving the frontend polling a job
    that can now never complete."""
    job = await get_owned_analysis_job(job_id, owner_user_id)
    if job is None or job.get("status") not in {"queued", "running"}:
        return job

    key = (owner_user_id, job.get("project_id", ""))
    if _running_jobs.get(key) == job_id:
        return job  # a live task in this process genuinely owns it

    age = _job_age_seconds(job)
    if age is not None and age < STALE_JOB_GRACE_SECONDS:
        return job

    interrupted_at = datetime.now(timezone.utc)
    await update_analysis_job(
        job_id,
        owner_user_id,
        {
            "status": "failed",
            "completed_at": interrupted_at,
            "error": "interrupted",
            "result": {
                "error": "Analysis interrupted because the server restarted. Retry analysis.",
            },
        },
    )
    job["status"] = "failed"
    job["error"] = "interrupted"
    job["completed_at"] = interrupted_at
    return job


async def _run_job(job_id: str, key: tuple[str, str], work: Callable[[str], Awaitable[dict]]) -> None:
    try:
        await update_analysis_job(job_id, key[0], {"status": "running", "started_at": datetime.now(timezone.utc)})
        result = await work(job_id)
        status = "partial" if result.get("partial") else "completed"
        await update_analysis_job(
            job_id,
            key[0],
            {"status": status, "completed_at": datetime.now(timezone.utc), "result": result},
        )
    except Exception as exc:
        await update_analysis_job(
            job_id,
            key[0],
            {"status": "failed", "completed_at": datetime.now(timezone.utc), "error": type(exc).__name__},
        )
        print(f"[analysis-job] failed job_id={job_id} error={type(exc).__name__}")
    finally:
        async with _guard:
            if _running_jobs.get(key) == job_id:
                _running_jobs.pop(key, None)
