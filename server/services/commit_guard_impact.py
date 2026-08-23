"""Commit Guard: blast-impact-delta engine and sensitive-surface detection.

Both entry points are 100% deterministic and offline -- no Groq/LLM call
anywhere in this file. compute_blast_delta re-runs the existing, already
deterministic services.blast_radius.build_blast_radius (with
include_ai=False) against a BASE and a HEAD snapshot and diffs the two
per-file blast scores/dependent counts. detect_sensitive_areas is pure
regex/keyword evidence matching against the HEAD content of changed files.

Field names below (score, direct_dependents, downstream_dependents, routes,
affected_routes, type) are read directly from services/blast_radius.py's
_rank_components / _build_components output -- not guessed.
"""

from __future__ import annotations

import re

from services.blast_radius import build_blast_radius
from services.git_history import snapshot_to_project

# Reused in STYLE (not imported) from hacker_lens.py / brutal_audit.py's
# _PRIORITY_PATTERNS -- kept self-contained here per spec. Order is the
# fixed vocabulary / output order for detect_sensitive_areas.
_SENSITIVE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("authentication", re.compile(r"(?i)\b(auth|login|logout|signup|password|jwt|oauth|session|get_current_user|get_request_user)\b")),
    ("admin", re.compile(r"(?i)\b(admin|is_admin|superuser|permission|role|privileg|authorize)\b")),
    ("database", re.compile(r"(?i)\b(sqlalchemy|sqlite3|psycopg|pymongo|mongo|database|db\.|cursor\(|execute\(|query\(|select\s+.+\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from)\b")),
    ("filesystem", re.compile(r"(?i)\b(open\(|Path\(|read_text\(|write_text\(|unlink\(|rmtree\(|shutil\.|zipfile\.|send_file)\b")),
    ("external_http", re.compile(r"(?i)\b(requests\.|httpx\.|urllib\.|aiohttp\.|webhook|stripe|twilio|boto3|\bs3\b)\b")),
    ("secrets", re.compile(r"(?i)\b(secret|api[_-]?key|credential|private[_-]?key|os\.environ|dotenv)\b")),
    ("privileged_operation", re.compile(r"(?i)\b(subprocess|shell=True|os\.system|exec\(|eval\(|delete|deploy|apply|fix|patch)\b")),
]


def detect_sensitive_areas(head_snapshot: dict[str, str], changed_paths: list[str]) -> list[str]:
    """Evidence-backed, deterministic tags for the changed files' HEAD
    content only. Returns tags in fixed-vocabulary order; a tag is included
    only when a real regex match was found."""
    combined = "\n".join(head_snapshot.get(path, "") for path in changed_paths if head_snapshot.get(path))
    return [tag for tag, pattern in _SENSITIVE_PATTERNS if pattern.search(combined)]


def _route_key(route: dict) -> tuple:
    return (route.get("file", ""), route.get("method", ""), route.get("path", ""))


async def compute_blast_delta(
    base_snapshot: dict[str, str],
    head_snapshot: dict[str, str],
    changed_paths: list[str],
) -> dict:
    base_result = await build_blast_radius(snapshot_to_project(base_snapshot), include_ai=False)
    head_result = await build_blast_radius(snapshot_to_project(head_snapshot), include_ai=False)

    base_by_path = {c["id"]: c for c in base_result.get("components", [])}
    head_by_path = {c["id"]: c for c in head_result.get("components", [])}

    components = []
    base_routes: set[tuple] = set()
    head_routes: set[tuple] = set()
    overall_before = 0.0
    overall_after = 0.0

    for path in changed_paths:
        before = base_by_path.get(path)
        after = head_by_path.get(path)
        if before is None and after is None:
            continue

        before_score = float(before["score"]) if before else 0.0
        after_score = float(after["score"]) if after else 0.0
        before_dependents = int(before["direct_dependents"]) if before else 0
        after_dependents = int(after["direct_dependents"]) if after else 0

        components.append(
            {
                "path": path,
                "before_score": before_score,
                "after_score": after_score,
                "delta": round(after_score - before_score, 3),
                "before_dependents": before_dependents,
                "after_dependents": after_dependents,
            }
        )
        overall_before += before_score
        overall_after += after_score
        if before:
            base_routes.update(_route_key(r) for r in before.get("affected_routes", []))
        if after:
            head_routes.update(_route_key(r) for r in after.get("affected_routes", []))

    summary = {
        "overall_before": round(overall_before, 3),
        "overall_after": round(overall_after, 3),
        "overall_delta": round(overall_after - overall_before, 3),
        "affected_routes_before": len(base_routes),
        "affected_routes_after": len(head_routes),
    }

    return {"components": components, "summary": summary}
