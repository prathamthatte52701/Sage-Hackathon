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
