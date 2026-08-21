"""Phase 7: structured pipeline observability.

Replaces ad-hoc print()-only visibility with a small per-review trace object
that records how long each stage took and how many candidates moved through
grounding/RAG, so a review that finishes in 2 seconds is explainable instead
of mysterious. Logged as one structured line per review (never in the normal
UI response) -- never includes API keys, auth headers, secrets, or full
source/prompt text, only counts and durations.
"""

import time


class StageTracer:
    """Usage:
        tracer = StageTracer("review")
        with tracer.stage("deterministic_ms"):
            ...
        tracer.count("ai_candidates", 5)
        tracer.log()
    """

    def __init__(self, name: str):
        self.name = name
        self._start = time.monotonic()
        self.durations_ms: dict[str, float] = {}
        self.counts: dict[str, int] = {}

    def stage(self, key: str):
        return _StageTimer(self, key)

    def count(self, key: str, value: int) -> None:
        self.counts[key] = value

    def total_ms(self) -> float:
        return round((time.monotonic() - self._start) * 1000, 1)

    def as_dict(self) -> dict:
        return {
            "pipeline": self.name,
            **{k: round(v, 1) for k, v in self.durations_ms.items()},
            "total_ms": self.total_ms(),
            **self.counts,
        }

    def log(self) -> None:
        parts = " ".join(f"{k}={v}" for k, v in self.as_dict().items() if k != "pipeline")
        print(f"[trace:{self.name}] {parts}")


class _StageTimer:
    def __init__(self, tracer: StageTracer, key: str):
        self.tracer = tracer
        self.key = key
        self._t0 = 0.0

    def __enter__(self):
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.tracer.durations_ms[self.key] = (time.monotonic() - self._t0) * 1000
        return False
