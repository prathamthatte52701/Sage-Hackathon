"""Simple in-memory fixed-window rate limiter, keyed by client IP.

Not session_id: a client-supplied session_id is trivially spoofable (it's
just a localStorage string with no auth behind it), so it adds no real
protection against someone hammering the API. IP is the honest choice for
a no-auth hackathon backend without pulling in a new dependency.
"""

import time

WINDOW_SECONDS = 60
MAX_REQUESTS = 30

_buckets: dict[str, list[float]] = {}


def check_rate_limit(key: str) -> bool:
    now = time.time()
    timestamps = _buckets.setdefault(key, [])
    while timestamps and timestamps[0] <= now - WINDOW_SECONDS:
        timestamps.pop(0)
    if len(timestamps) >= MAX_REQUESTS:
        return False
    timestamps.append(now)
    return True
