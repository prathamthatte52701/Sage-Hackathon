import asyncio
from types import SimpleNamespace

import main as main_module
from services import rate_limit as rate_limit_module


def _request(path: str, ip: str) -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(path=path), client=SimpleNamespace(host=ip))


async def _call_next(_request) -> SimpleNamespace:
    return SimpleNamespace(status_code=200)


def _hit(path: str, ip: str, times: int) -> list[int]:
    return [
        asyncio.run(main_module.rate_limit_middleware(_request(path, ip), _call_next)).status_code
        for _ in range(times)
    ]


def test_analysis_job_polling_is_exempt_from_rate_limit():
    # The frontend polls this endpoint every 1s for up to 2 minutes during a
    # single analyze call -- well past the general 30/60s budget. It must
    # never 429, or a real analysis run gets randomly killed mid-poll.
    rate_limit_module._buckets.clear()
    statuses = _hit("/api/analysis-jobs/job-1", "10.0.0.1", 60)
    assert all(status == 200 for status in statuses)


def test_automation_status_polling_is_exempt_from_rate_limit():
    rate_limit_module._buckets.clear()
    statuses = _hit("/api/projects/project-1/automation/status", "10.0.0.3", 60)
    assert all(status == 200 for status in statuses)


def test_commit_guard_status_polling_is_exempt_from_rate_limit():
    rate_limit_module._buckets.clear()
    statuses = _hit("/api/projects/project-1/commit-guard/status", "10.0.0.4", 60)
    assert all(status == 200 for status in statuses)


def test_other_api_routes_are_still_rate_limited():
    # The exemption must be scoped to analysis-jobs only -- everything else
    # on /api/* still needs real IP throttling to stay a working guard.
    rate_limit_module._buckets.clear()
    statuses = _hit("/api/projects/abc", "10.0.0.2", 35)
    assert 429 in statuses
    assert statuses[:30] == [200] * 30
