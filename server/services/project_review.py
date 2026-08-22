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
import re

from models.schemas import Issue
from services.analyzer import SOURCE_LANGUAGES, is_test_file
from services.groq_client import GroqUnavailableError, call_groq
from services.grounding import ground_issue
from services.prompt_builder import build_quality_review_prompt
from services.structural import analyze_python_source, line_range
from services.tracing import StageTracer
from config import GROQ_GLOBAL_CONCURRENCY, PROJECT_AI_CALL_BUDGET

# Bounds -- deliberately conservative. A 20000-file "scale test" project must
# not translate into 20000 Groq calls; reviewing the largest/most-central
# source files gives more signal per call than reviewing every trivial one.
MAX_FILES_REVIEWED = 40
MAX_CHUNK_CHARS = 6000
MAX_CHUNKS_PER_FILE = 8
# This semaphore is intentionally process-wide. A semaphore created inside
# each project review only limits one request while allowing concurrent jobs
# to multiply provider traffic.
GLOBAL_AI_SEMAPHORE = asyncio.Semaphore(GROQ_GLOBAL_CONCURRENCY)
# Backwards-compatible public constant for callers that supply their own
# semaphore in focused tests; production scheduling uses the global semaphore.
CONCURRENCY_LIMIT = GROQ_GLOBAL_CONCURRENCY
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_RULE_GROUPS = {
    "subprocess_shell_true": "command_execution",
    "os_system_call": "command_execution",
    "spawn_shell_true": "command_execution",
    "unsafe_deserialization": "unsafe_deserialization",
    "permissive_cors": "permissive_cors",
    "blocking_call_in_async": "blocking_async",
    "ssrf_untrusted_url": "ssrf",
    "dangerous_eval": "dynamic_code_execution",
    "sql_concat": "sql_injection",
}


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


def _line_count(text: str) -> int:
    return len((text or "").splitlines())


def _with_header(path: str, start_line: int, body: str, symbol: str = "module") -> str:
    end_line = start_line + max(_line_count(body) - 1, 0)
    return f"# FILE: {path}\n# LINES: {start_line}-{end_line}\n# SYMBOL: {symbol}\n{body}"


def _fallback_chunks(content: str, path: str = "", start_line: int = 1) -> list[str]:
    if len(content) <= MAX_CHUNK_CHARS:
        return [_with_header(path, start_line, content)]

    lines = content.splitlines(keepends=True)
    chunks = []
    current = []
    current_len = 0
    current_start = start_line
    line_no = start_line
    for line in lines:
        if current_len + len(line) > MAX_CHUNK_CHARS and current:
            chunks.append(_with_header(path, current_start, "".join(current)))
            if len(chunks) >= MAX_CHUNKS_PER_FILE:
                return chunks
            current, current_len = [], 0
            current_start = line_no
        current.append(line)
        current_len += len(line)
        line_no += 1
    if current and len(chunks) < MAX_CHUNKS_PER_FILE:
        chunks.append(_with_header(path, current_start, "".join(current)))
    return chunks


def _chunk_content(content: str, path: str = "", language: str = "") -> list[str]:
    if language == "python":
        module = analyze_python_source(content)
        if module.parse_error is None:
            units: list[tuple[int, int, str]] = []
            units.extend((fn.start_line, fn.end_line, f"function {fn.name}") for fn in module.functions)
            units.extend((cls.start_line, cls.end_line, f"class {cls.name}") for cls in module.classes)
            units.sort(key=lambda item: (item[0], -(item[1] - item[0])))
            selected: list[tuple[int, int, str]] = []
            covered_until = 0
            for start, end, symbol in units:
                if start <= covered_until:
                    continue
                if start > covered_until + 1:
                    selected.append((covered_until + 1, start - 1, "module"))
                selected.append((start, end, symbol))
                covered_until = end
            total_lines = _line_count(content)
            if covered_until < total_lines:
                selected.append((covered_until + 1, total_lines, "module"))

            chunks = []
            for start, end, symbol in selected:
                body = line_range(content, start, end)
                if not body.strip():
                    continue
                if len(body) <= MAX_CHUNK_CHARS:
                    chunks.append(_with_header(path, start, body, symbol))
                else:
                    chunks.extend(_fallback_chunks(body, path, start))
                if len(chunks) >= MAX_CHUNKS_PER_FILE:
                    return chunks[:MAX_CHUNKS_PER_FILE]
            if chunks:
                return chunks[:MAX_CHUNKS_PER_FILE]

    return _fallback_chunks(content, path, 1)


def _issue_to_project_finding(issue: Issue, path: str) -> dict:
    severity_map = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}
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


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9_.]+", " ", value or "").lower()).strip()


def _root_group(finding: dict) -> str:
    rule = finding.get("rule") or ""
    if rule in _RULE_GROUPS:
        return _RULE_GROUPS[rule]
    title = _normalize_text(f"{finding.get('rule', '')} {finding.get('message', '')}")
    for needle, group in (
        ("shell true", "command_execution"),
        ("command injection", "command_execution"),
        ("yaml load", "unsafe_deserialization"),
        ("pickle", "unsafe_deserialization"),
        ("cors", "permissive_cors"),
        ("time.sleep", "blocking_async"),
        ("blocking", "blocking_async"),
    ):
        if needle in title:
            return group
    return finding.get("category") or rule or title


def _dedupe_key(finding: dict) -> tuple:
    line = int(finding.get("line") or 0)
    evidence = _normalize_text(finding.get("evidence", ""))
    sink = evidence[:90] or _normalize_text(finding.get("message", ""))[:90]
    return (finding.get("file"), _root_group(finding), line // 3, sink)


def _merge_duplicate(base: dict, incoming: dict) -> dict:
    merged = dict(base)
    if _SEVERITY_RANK.get(incoming.get("severity"), 0) > _SEVERITY_RANK.get(base.get("severity"), 0):
        merged["severity"] = incoming.get("severity")
        merged["message"] = incoming.get("message") or merged.get("message")
    sources = set(str(merged.get("source", "deterministic")).split("+"))
    sources.add(incoming.get("source") or "deterministic")
    merged["source"] = "+".join(sorted(s for s in sources if s))
    merged["confidence"] = "high" if "deterministic" in merged["source"] else merged.get("confidence", "medium")
    if incoming.get("fix_suggestion") and not merged.get("fix_suggestion"):
        merged["fix_suggestion"] = incoming.get("fix_suggestion")
    base.update(merged)
    return merged


def _dedupe_against_deterministic(quality_findings: list[dict], deterministic_by_file: dict[str, list[dict]]) -> list[dict]:
    kept = []
    existing_by_key = {}
    for deterministic in [item for values in deterministic_by_file.values() for item in values]:
        existing_by_key[_dedupe_key(deterministic)] = deterministic
    for qf in quality_findings:
        key = _dedupe_key(qf)
        if key in existing_by_key:
            _merge_duplicate(existing_by_key[key], qf)
            continue
        if key in {_dedupe_key(item) for item in kept}:
            for idx, item in enumerate(kept):
                if _dedupe_key(item) == key:
                    kept[idx] = _merge_duplicate(item, qf)
                    break
            continue
        kept.append(qf)
    return kept


async def _review_chunk(path: str, language: str, chunk: str, semaphore: asyncio.Semaphore | None = None) -> tuple[list[dict], bool]:
    """Returns (grounded_finding_dicts, groq_was_called)."""
    async with (semaphore or GLOBAL_AI_SEMAPHORE):
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

    tasks = []
    task_meta = []
    for file_entry in reviewed:
        path = file_entry["path"]
        language = file_entry.get("language")
        chunks = _chunk_content(file_entry["content"], path, language)
        for chunk in chunks:
            if len(tasks) >= PROJECT_AI_CALL_BUDGET:
                break
            tasks.append(_review_chunk(path, language, chunk, GLOBAL_AI_SEMAPHORE))
            task_meta.append(path)
        if len(tasks) >= PROJECT_AI_CALL_BUDGET:
            break

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
        "eligible_files": len(eligible),
        "deterministic_files": len([f for f in project.get("files", []) if f.get("language") in SOURCE_LANGUAGES and f.get("content")]),
        "ai_reviewed_files": len(reviewed),
        "files_eligible": len(eligible),
        "files_reviewed": len(reviewed),
        "files_skipped": len(skipped),
        "ai_chunks_total": len(tasks),
        "ai_chunks_completed": groq_calls,
        "chunks_reviewed": len(tasks),
        "groq_calls": groq_calls,
        "failed_ai_chunks": len(tasks) - groq_calls,
        "semantic_coverage": "partial" if skipped or (len(tasks) != groq_calls) or len(tasks) >= PROJECT_AI_CALL_BUDGET else "complete",
        "partial_reasons": ([f"{len(skipped)} eligible file(s) exceeded AI review budget"] if skipped else [])
        + ([f"{len(tasks) - groq_calls} AI chunk(s) failed or were skipped"] if len(tasks) != groq_calls else [])
        + ([f"AI call budget of {PROJECT_AI_CALL_BUDGET} reached"] if len(tasks) >= PROJECT_AI_CALL_BUDGET else []),
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
