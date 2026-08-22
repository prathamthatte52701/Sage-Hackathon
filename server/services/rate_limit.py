"""Simple in-memory fixed-window rate limiter, keyed by client IP.

Not session_id: a client-supplied session_id is trivially spoofable (it's
just a localStorage string with no auth behind it), so it adds no real
protection against someone hammering the API. IP is the honest choice for
a no-auth hackathon backend without pulling in a new dependency.

Process-local only: buckets live in this process's memory, not shared
across workers/replicas. Fine for a single-process hackathon deploy; a
multi-worker/multi-instance deploy would need a shared store (e.g. Redis)
for the limit to hold globally instead of per-process.
"""

import time

WINDOW_SECONDS = 60
MAX_REQUESTS = 30

_buckets: dict[str, list[float]] = {}


def check_rate_limit(key: str, max_requests: int = MAX_REQUESTS, window_seconds: int = WINDOW_SECONDS) -> bool:
    now = time.time()
    timestamps = _buckets.setdefault(key, [])
    while timestamps and timestamps[0] <= now - window_seconds:
        timestamps.pop(0)
    if len(timestamps) >= max_requests:
        return False
    timestamps.append(now)
    return True
