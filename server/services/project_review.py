"""Phase 13: AI quality review for uploaded project files.

Before this, project ZIP analysis (services/analyzer.py) only ran deterministic
regex rules -- no Groq call, no knowledge retrieval, no grounding. That made
project analysis meaningfully shallower than paste-code review, which runs
the full deterministic + pre-review RAG + AI quality review + grounding +
per-finding RAG pipeline. This module runs that same quality-review stage
against a project's own source files, bounded so it can't send hundreds of
uncontrolled Groq calls for a large project.
"""

import asyncio

from models.schemas import Issue
from services.analyzer import SOURCE_LANGUAGES, is_test_file
from services.groq_client import GroqUnavailableError, call_groq
from services.grounding import ground_issue
from services.prompt_builder import build_quality_review_prompt
from services.tracing import StageTracer

# Bounds -- deliberately conservative. A 20000-file "scale test" project must
# not translate into 20000 Groq calls; reviewing the largest/most-central
# source files gives more signal per call than reviewing every trivial one.
MAX_FILES_REVIEWED = 40
MAX_CHUNK_CHARS = 6000
MAX_CHUNKS_PER_FILE = 2
CONCURRENCY_LIMIT = 4


def _eligible_files(project: dict) -> list[dict]:
    files = [
        f
        for f in project.get("files", [])
        if f.get("language") in SOURCE_LANGUAGES and f.get("content") and not is_test_file(f.get("path", ""))
    ]
    # Prioritize larger files first -- more surface area for real issues per
    # Groq call than a five-line utility file, within the same file budget.
    files.sort(key=lambda f: len(f.get("content") or ""), reverse=True)
    return files


def _chunk_content(content: str) -> list[str]:
    if len(content) <= MAX_CHUNK_CHARS:
        return [content]
    lines = content.splitlines(keepends=True)
    chunks = []
    current = []
    current_len = 0
    for line in lines:
        if current_len + len(line) > MAX_CHUNK_CHARS and current:
            chunks.append("".join(current))
            if len(chunks) >= MAX_CHUNKS_PER_FILE:
                return chunks
            current, current_len = [], 0
        current.append(line)
        current_len += len(line)
    if current and len(chunks) < MAX_CHUNKS_PER_FILE:
        chunks.append("".join(current))
    return chunks


def _issue_to_project_finding(issue: Issue, path: str) -> dict:
    severity_map = {"critical": "high", "medium": "medium", "low": "low"}
    return {
        "file": path,
        "line": issue.line or 0,
        "rule": issue.rule or f"ai_quality_{issue.category}",
        "severity": severity_map.get(issue.severity, "medium"),
        "category": issue.category,
        "message": issue.issue,
        "evidence": issue.evidence,
        "confidence": "high" if issue.confidence >= 0.7 else "medium" if issue.confidence >= 0.4 else "low",
        "evidence_type": "ai_quality_review",
        "fix_suggestion": issue.fix_suggestion,
        "source": "ai_quality",
    }


def _dedupe_against_deterministic(quality_findings: list[dict], deterministic_by_file: dict[str, list[dict]]) -> list[dict]:
    kept = []
    for qf in quality_findings:
        existing = deterministic_by_file.get(qf["file"], [])
        is_dup = any(
            df.get("line") == qf.get("line") and df.get("category") == qf.get("category") for df in existing
        )
        if not is_dup:
            kept.append(qf)
    return kept


async def _review_chunk(path: str, language: str, chunk: str, semaphore: asyncio.Semaphore) -> tuple[list[dict], bool]:
    """Returns (grounded_finding_dicts, groq_was_called)."""
    async with semaphore:
        try:
            raw = await call_groq([{"role": "user", "content": build_quality_review_prompt(chunk, language, None)}])
        except GroqUnavailableError:
            return [], False

    import json
    import re

    def extract_json(text):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            match = re.search(r"\{.*\}", text or "", re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    return None
        return None

    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        return [], True

    findings = []
    for raw_issue in parsed.get("issues") or []:
        try:
            issue = Issue(**{k: v for k, v in raw_issue.items() if k in Issue.model_fields})
        except Exception:
            continue
        grounded, _reason = ground_issue(issue, chunk)
        if grounded:
            findings.append(_issue_to_project_finding(issue, path))
    return findings, True


async def run_ai_quality_review(project: dict) -> dict:
    """Runs AI quality review across eligible project source files, bounded
    and concurrency-limited. Returns coverage metadata; mutates
    project["findings"] in place by appending grounded, deduplicated AI
    findings. Never raises -- a Groq/grounding failure just means fewer
    findings, not a broken project analysis (deterministic findings from
    analyze_project already ran and are untouched)."""
    tracer = StageTracer("project_ai_review")
    eligible = _eligible_files(project)
    reviewed = eligible[:MAX_FILES_REVIEWED]
    skipped = eligible[MAX_FILES_REVIEWED:]

    deterministic_by_file: dict[str, list[dict]] = {}
    for finding in project.get("findings", []):
        deterministic_by_file.setdefault(finding.get("file"), []).append(finding)

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    tasks = []
    task_meta = []
    for file_entry in reviewed:
        path = file_entry["path"]
        language = file_entry.get("language")
        chunks = _chunk_content(file_entry["content"])
        for chunk in chunks:
            tasks.append(_review_chunk(path, language, chunk, semaphore))
            task_meta.append(path)

    with tracer.stage("groq_ms"):
        results = await asyncio.gather(*tasks) if tasks else []

    all_findings = []
    groq_calls = 0
    for findings, called in results:
        all_findings.extend(findings)
        groq_calls += 1 if called else 0

    with tracer.stage("grounding_and_dedup_ms"):
        deduped = _dedupe_against_deterministic(all_findings, deterministic_by_file)
    project.setdefault("findings", []).extend(deduped)

    coverage = {
        "files_discovered": len(project.get("files", [])),
        "files_eligible": len(eligible),
        "files_reviewed": len(reviewed),
        "files_skipped": len(skipped),
        "chunks_reviewed": len(tasks),
        "groq_calls": groq_calls,
        "ai_candidate_count": sum(len(f) for f, _ in results),
        "ai_finding_count": len(deduped),
        "project_total_ms": tracer.total_ms(),
    }
    project["ai_review_coverage"] = coverage
    tracer.count("files_reviewed", len(reviewed))
    tracer.count("groq_calls", groq_calls)
    tracer.count("ai_findings_accepted", len(deduped))
    tracer.log()
    return coverage
