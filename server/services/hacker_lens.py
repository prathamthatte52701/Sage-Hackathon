"""Hacker Mode: independent adversarial AI review of an uploaded repository.

Deliberately separate from services/reasoning_engine.py -- that module always
grounds itself on an existing deterministic finding. Hacker Mode has no
finding to ground on; it reasons freely, from an attacker's perspective, over
a bounded slice of the repository. It NEVER queries knowledge/retrieval (no
RAG) and never writes to project["findings"]/security_findings -- it is a
read-only, additive report, not a second source of findings.
"""

import re

from models.schemas import HackerLensEvidence, HackerLensObservation, HackerLensReport, HackerLensRiskPath, HackerLensTopTarget
from services.analyzer import SOURCE_LANGUAGES, is_test_file
from services.groq_client import GroqUnavailableError, call_groq
from services.prompt_builder import build_hacker_lens_prompt
from services.project_review import GLOBAL_AI_SEMAPHORE
from services.reasoning_engine import _extract_json

# Bounds mirror services/project_review.py's philosophy: bounded, not
# exhaustive. A single Hacker Mode call must stay inside the existing Groq
# token/latency budget, not scale with repository size.
MAX_FILES = 22
MAX_FILE_CHARS = 3200
MAX_TOTAL_CONTEXT_CHARS = 42000

_PRIORITY_PATTERNS = [
    (re.compile(r"(?i)\b(route|router|endpoint|views?|controller)\b"), 5),
    (re.compile(r"(?i)\b(auth|login|logout|session|jwt|oauth|password|token|signup)\b"), 5),
    (re.compile(r"(?i)\b(middleware|guard|permission|role|admin|privileg)\b"), 4),
    (re.compile(r"(?i)\b(upload|multipart|filename|filesystem|\bfs\b|storage)\b"), 4),
    (re.compile(r"(?i)\b(db|database|mongo|sql|query|cursor|model)\b"), 3),
    (re.compile(r"(?i)\b(http|requests|axios|fetch|urllib|httpx)\b"), 2),
    (re.compile(r"(?i)\b(config|secret|env|api[_-]?key|credential)\b"), 3),
]


def _priority_score(path: str, content: str) -> int:
    haystack = f"{path}\n{content[:2000]}"
    return sum(weight for pattern, weight in _PRIORITY_PATTERNS if pattern.search(haystack))


def _select_files(project: dict) -> list[dict]:
    files = [
        f
        for f in project.get("files", [])
        if f.get("language") in SOURCE_LANGUAGES and f.get("content") and not is_test_file(f.get("path", ""))
    ]
    files.sort(key=lambda f: _priority_score(f.get("path", ""), f.get("content", "")), reverse=True)
    return files[:MAX_FILES]


def _build_context(project: dict) -> tuple[str, list[str]]:
    parts: list[str] = []
    included: list[str] = []
    total = 0
    for file_entry in _select_files(project):
        path = file_entry["path"]
        content = (file_entry.get("content") or "")[:MAX_FILE_CHARS]
        block = f"--- FILE: {path} ---\n{content}\n"
        if total + len(block) > MAX_TOTAL_CONTEXT_CHARS:
            break
        parts.append(block)
        included.append(path)
        total += len(block)
    return "\n".join(parts), included


def _valid_file_paths(project: dict) -> set[str]:
    return {f.get("path", "") for f in project.get("files", []) if f.get("path")}


def _coerce_evidence(raw, valid_files: set[str]) -> list[HackerLensEvidence]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:6]:
        if not isinstance(item, dict):
            continue
        file_path = item.get("file")
        if not isinstance(file_path, str):
            file_path = ""
        # Only keep evidence pointing at a file that genuinely exists in this
        # project -- a hallucinated path is worse than no evidence at all.
        if file_path and file_path not in valid_files:
            continue
        line = item.get("line")
        if not isinstance(line, int) or isinstance(line, bool) or line <= 0:
            line = None
        function = item.get("function") if isinstance(item.get("function"), str) else ""
        route = item.get("route") if isinstance(item.get("route"), str) else ""
        if not (file_path or function or route):
            continue
        out.append(HackerLensEvidence(file=file_path, line=line, function=function, route=route))
    return out


def _coerce_observation(raw, valid_files: set[str]) -> HackerLensObservation | None:
    if not isinstance(raw, dict):
        return None
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    risk = raw.get("risk")
    if risk not in ("critical", "high", "medium", "low"):
        risk = "low"
    evidence = _coerce_evidence(raw.get("evidence"), valid_files)
    return HackerLensObservation(
        title=title.strip(),
        risk=risk,
        reason=raw.get("reason") if isinstance(raw.get("reason"), str) else "",
        evidence=evidence,
        potential_impact=raw.get("potential_impact") if isinstance(raw.get("potential_impact"), str) else "",
        hardening_action=raw.get("hardening_action") if isinstance(raw.get("hardening_action"), str) else "",
        verified=any(e.file for e in evidence),
    )


def _coerce_top_targets(raw, valid_files: set[str]) -> list[HackerLensTopTarget]:
    if not isinstance(raw, list):
        return []
    out = []
    for index, item in enumerate(raw[:5], start=1):
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        rank = item.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank <= 0:
            rank = index
        out.append(
            HackerLensTopTarget(
                rank=rank,
                title=title.strip(),
                reason=item.get("reason") if isinstance(item.get("reason"), str) else "",
                evidence=_coerce_evidence(item.get("evidence"), valid_files),
            )
        )
    return out


def _coerce_risk_paths(raw, valid_files: set[str]) -> list[HackerLensRiskPath]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:4]:
        if not isinstance(item, dict):
            continue
        steps = item.get("steps")
        steps = [s for s in steps if isinstance(s, str) and s.strip()][:6] if isinstance(steps, list) else []
        if not steps:
            continue
        label = item.get("label")
        out.append(
            HackerLensRiskPath(
                label=label.strip() if isinstance(label, str) and label.strip() else " -> ".join(steps[:2]),
                steps=steps,
                evidence=_coerce_evidence(item.get("evidence"), valid_files),
            )
        )
    return out


def _coerce_string_list(raw, limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [s.strip() for s in raw if isinstance(s, str) and s.strip()][:limit]


# Fixed thresholds -- the model's own 0-10 score is clamped and re-labeled
# from these, never taken as the model's self-assigned label. Keeps
# "HIGH"/"CRITICAL" etc meaning the same thing across every report.
def _score_label(score: float) -> str:
    if score >= 8.5:
        return "critical"
    if score >= 6.5:
        return "high"
    if score >= 3.5:
        return "medium"
    return "low"


def _build_report(raw: dict, valid_files: set[str], included_files: list[str]) -> HackerLensReport:
    data = raw if isinstance(raw, dict) else {}

    score = data.get("attack_surface_score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        score = 0.0
    score = max(0.0, min(10.0, float(score)))

    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        summary = "Hacker Mode did not return a usable summary for this analysis."

    return HackerLensReport(
        summary=summary.strip(),
        attack_surface_score=score,
        attack_surface_label=_score_label(score),
        score_reasoning=data.get("score_reasoning") if isinstance(data.get("score_reasoning"), str) else "",
        top_targets=_coerce_top_targets(data.get("top_targets"), valid_files),
        attack_surfaces=_coerce_string_list(data.get("attack_surfaces"), 6),
        risk_paths=_coerce_risk_paths(data.get("risk_paths"), valid_files),
        adversarial_observations=[
            o for o in (_coerce_observation(item, valid_files) for item in (data.get("adversarial_observations") or [])[:6]) if o
        ],
        hacker_hypotheses=[
            o for o in (_coerce_observation(item, valid_files) for item in (data.get("hacker_hypotheses") or [])[:5]) if o
        ],
        hardening_priorities=_coerce_string_list(data.get("hardening_priorities"), 6),
        files_analyzed=included_files,
    )


async def run_hacker_lens(project: dict) -> HackerLensReport:
    repo_context, included_files = _build_context(project)
    if not included_files:
        return HackerLensReport(
            summary="No eligible source files were found to analyze in this project.",
            error="no_eligible_files",
        )

    valid_files = _valid_file_paths(project)
    prompt = build_hacker_lens_prompt(repo_context, included_files)
    messages = [{"role": "user", "content": prompt}]

    try:
        async with GLOBAL_AI_SEMAPHORE:
            raw = await call_groq(messages)
        parsed = _extract_json(raw)
        if parsed is None:
            retry_messages = [
                {
                    "role": "user",
                    "content": prompt
                    + "\n\nYour previous response was not valid JSON. Respond with ONLY the JSON object, nothing else.",
                }
            ]
            async with GLOBAL_AI_SEMAPHORE:
                raw = await call_groq(retry_messages)
            parsed = _extract_json(raw)
    except GroqUnavailableError as exc:
        return HackerLensReport(
            summary="Hacker Mode AI analysis is currently unavailable. Please retry.",
            files_analyzed=included_files,
            error=str(exc),
        )

    if parsed is None:
        return HackerLensReport(
            summary="Hacker Mode AI returned an unparseable response. Please retry.",
            files_analyzed=included_files,
            error="invalid_model_output",
        )

    return _build_report(parsed, valid_files, included_files)
