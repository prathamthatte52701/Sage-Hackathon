import json
import re

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from db.mongo import get_history, save_review
from knowledge.retrieval import _GENERIC_QUERY_WORDS, redact_sensitive_query_text, retrieve_knowledge
from knowledge.seed_data import KNOWLEDGE_RECORDS
from models.schemas import FindingTransform, Issue, PasteFixRequest, ReviewRequest, ReviewResponse
from services.auth import get_current_user
from services.patching import build_patch_metadata
from services.groq_client import GroqUnavailableError, call_groq
from services.analyzers.rules import run_rules
from services.grounding import ground_issues
from services.tracing import StageTracer
from services.prompt_builder import build_quality_review_prompt, build_transform_prompt

router = APIRouter()

ERROR_RESPONSE = {"error": "Could not analyze this code, please try again"}
FIX_ERROR_RESPONSE = {"error": "Could not generate a safe fix for this issue, please try again"}


class ReviewRequestIn(ReviewRequest):
    session_id: str


def _extract_json(raw_text: str):
    """Try direct json.loads, then fall back to extracting {...} substring."""
    try:
        return json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        pass

    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _build_issue(raw: dict) -> Issue:
    """Construct an Issue from a raw dict, coercing/dropping bad fields instead of crashing."""
    data = dict(raw) if isinstance(raw, dict) else {}

    line = data.get("line")
    if not isinstance(line, int):
        data.pop("line", None)

    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        data.pop("confidence", None)

    needs_human_review = data.get("needs_human_review")
    if not isinstance(needs_human_review, bool):
        data.pop("needs_human_review", None)

    return Issue(**{k: v for k, v in data.items() if k in Issue.model_fields})


def _build_review_response(parsed: dict) -> ReviewResponse:
    try:
        return ReviewResponse.model_validate(parsed)
    except Exception:
        pass

    issues = []
    for raw_issue in (parsed.get("issues") or []) if isinstance(parsed, dict) else []:
        try:
            issues.append(_build_issue(raw_issue))
        except Exception:
            continue  # skip the single broken issue, don't kill the request

    summary = parsed.get("summary", "") if isinstance(parsed, dict) else ""
    if not isinstance(summary, str):
        summary = ""

    return ReviewResponse(issues=issues, summary=summary)


def _build_quality_issues(parsed: dict) -> tuple[list[Issue], str]:
    issues = []
    for raw_issue in (parsed.get("issues") or []) if isinstance(parsed, dict) else []:
        try:
            issue = _build_issue(raw_issue)
            issue.source = "ai_quality"
            issues.append(issue)
        except Exception:
            continue
    summary = parsed.get("summary", "") if isinstance(parsed, dict) else ""
    return issues, summary if isinstance(summary, str) else ""


def _prefer_finally_cleanup(original: str, fixed: str, issue: dict) -> str:
    issue_text = " ".join(str(issue.get(field, "")) for field in ("issue", "fix_suggestion", "evidence")).lower()
    if "pendinguser" not in issue_text.replace("_", ""):
        return fixed
    if "finally" in (fixed or ""):
        return fixed
    if "pendingUser" not in fixed or "catch" not in fixed:
        return fixed

    pattern = re.compile(
        r"(?P<prefix>pendingUser\s*=\s*[^;\n]+;\s*\n\s*try\s*\{\s*\n)"
        r"(?P<body>.*?)"
        r"\n\s*\}\s*catch\s*\([^)]*\)\s*\{\s*\n"
        r"\s*pendingUser\s*=\s*null;\s*\n"
        r"\s*throw\s+[^;\n]+;\s*\n"
        r"\s*\}",
        re.DOTALL,
    )
    match = pattern.search(fixed)
    if not match:
        return fixed

    pending_indent = re.search(r"(?m)^(?P<indent>\s*)pendingUser\s*=", fixed)
    block_indent = pending_indent.group("indent") if pending_indent else ""
    inner_indent = f"{block_indent}  "
    replacement = (
        f"{match.group('prefix')}{match.group('body')}\n"
        f"{block_indent}}} finally {{\n"
        f"{inner_indent}pendingUser = null;\n"
        f"{block_indent}}}"
    )
    return fixed[: match.start()] + replacement + fixed[match.end() :]


def _build_transform_response(parsed: dict, issue: dict, code: str) -> FindingTransform:
    original = ""
    fixed = ""
    if isinstance(parsed, dict):
        original = parsed.get("original_snippet") or parsed.get("original_code") or ""
        fixed = parsed.get("proposed_fix") or parsed.get("fixed_code") or ""
        fixed = _prefer_finally_cleanup(original, fixed, issue)

    explanation = parsed.get("explanation", "") if isinstance(parsed, dict) else ""
    if isinstance(explanation, list):
        explanation_bullets = [str(item) for item in explanation[:4]]
        explanation_text = " ".join(explanation_bullets)
    else:
        explanation_text = str(explanation or "AI fix generated.")
        explanation_bullets = [part.strip("- ").strip() for part in explanation_text.split(".") if part.strip()][:4]

    patch = build_patch_metadata(code, original, fixed, filename="fixed-code")
    can_apply = bool(patch.get("can_apply"))
    diff = patch.get("diff", "")

    return FindingTransform(
        finding_id=str(issue.get("line") or ""),
        rule_id=str(issue.get("rule") or issue.get("category") or ""),
        file="fixed-code",
        line=int(issue.get("line") or 0) if str(issue.get("line") or "").isdigit() else 0,
        summary=parsed.get("summary", "") if isinstance(parsed, dict) else "",
        original_snippet=original,
        proposed_fix=fixed,
        original_code=original,
        fixed_code=fixed,
        diff=diff,
        explanation=explanation_text,
        explanation_bullets=explanation_bullets,
        can_apply=can_apply,
        apply_failure_reason=patch.get("apply_failure_reason", ""),
        target_file="fixed-code",
        document_type="paste",
        start_line=int(patch.get("start_line") or issue.get("line") or 0) if str(patch.get("start_line") or issue.get("line") or "").isdigit() else 0,
        end_line=int(patch.get("end_line") or issue.get("line") or 0) if str(patch.get("end_line") or issue.get("line") or "").isdigit() else 0,
        target_start=int(patch.get("target_start") or 0),
        target_end=int(patch.get("target_end") or 0),
        source_hash=patch.get("source_hash", ""),
        confidence=parsed.get("confidence", 0.0) if isinstance(parsed, dict) else 0.0,
    )


def _apply_confidence_sanity_checks(response: ReviewResponse) -> None:
    for issue in response.issues:
        if issue.category == "security" and not issue.line:
            issue.confidence = max(0.0, issue.confidence - 0.2)
        if issue.severity == "critical" and issue.confidence < 0.5:
            issue.needs_human_review = True


def _static_issue_from_finding(finding: dict) -> Issue:
    severity = finding.get("severity", "low")
    if severity == "high":
        severity = "critical"
    category = finding.get("category", "best_practice")
    if category not in Issue.model_fields["category"].annotation.__args__:
        category = "best_practice"
    return Issue(
        line=finding.get("line", 0) or 0,
        severity=severity if severity in ("critical", "medium", "low") else "low",
        category=category,
        issue=finding.get("message", ""),
        fix_suggestion="Review the deterministic evidence and apply the matching secure pattern.",
        confidence=0.65,
        needs_human_review=finding.get("severity") in ("critical", "high"),
        rule=finding.get("rule", ""),
        evidence=finding.get("evidence", ""),
        source="deterministic",
    )


def _deterministic_review_response(code: str, language: str, reason: str = "") -> ReviewResponse:
    findings = run_rules("snippet", language, code)
    issues = [_static_issue_from_finding(finding) for finding in findings]
    if issues:
        summary = f"{len(issues)} deterministic issue(s) found"
        if reason:
            summary += f"; AI reasoning unavailable ({reason})"
    else:
        summary = "No deterministic issues found"
        if reason:
            summary += f"; AI reasoning unavailable ({reason})"
    return ReviewResponse(issues=issues, deterministic_findings=issues, ai_quality_review=[], summary=summary)


_JS_STRONG_RE = re.compile(r"\b(export\s+function|export\s+const|const\s+\w+\s*=|let\s+\w+\s*=|=>|console\.|module\.exports|require\s*\()")
_TS_STRONG_RE = re.compile(r"\b(interface|type\s+\w+\s*=|:\s*(string|number|boolean|unknown|Record<)|as\s+const)\b")
_PY_STRONG_RE = re.compile(r"(^|\n)\s*(def\s+\w+\s*\(|import\s+\w+|from\s+\w+\s+import|print\s*\(|if\s+__name__\s*==)", re.MULTILINE)


def detect_language(code: str, selected_language: str) -> dict:
    text = code or ""
    detected = selected_language
    confidence = "low"
    signals = []

    if _TS_STRONG_RE.search(text):
        detected = "typescript"
        confidence = "high"
        signals.append("typescript syntax")
    elif _JS_STRONG_RE.search(text):
        detected = "javascript"
        confidence = "high"
        signals.append("javascript syntax")
    elif _PY_STRONG_RE.search(text):
        detected = "python"
        confidence = "high"
        signals.append("python syntax")

    mismatch = confidence == "high" and detected != selected_language
    return {
        "selected": selected_language,
        "detected": detected,
        "effective": detected if mismatch else selected_language,
        "confidence": confidence,
        "mismatch": mismatch,
        "signals": signals,
    }


# (signal_key, KB-domain hint phrase, regex) -- scanned across the WHOLE
# source (not just a truncated prefix) so a risk near the bottom of a long
# file still surfaces. One representative line per matched signal is pulled
# into the query instead of a raw truncated dump, so the query stays compact
# (and useful to a 256-token local embedder) regardless of file length, and
# the KB domain hints stay proportional to what's actually IN the file
# instead of a fixed validation/numeric/date bias.
_SIGNAL_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("llm_ai_provider", "external AI/LLM trust boundary, prompt injection, third-party data privacy, data minimization",
     re.compile(r"\b(openai|groq|anthropic|chat/completions|chat\.completions|llm)\b", re.I)),
    ("outbound_http", "external service reliability, outbound timeouts, malformed response handling",
     re.compile(r"\bfetch\s*\(|\baxios\.|\brequests\.(get|post|put|delete)\(|\bhttpx\.")),
    ("json_parsing", "malformed/untrusted response handling",
     re.compile(r"JSON\.parse\(")),
    ("cache_state", "caching, cache invalidation, stale derived data",
     re.compile(r"\bcache\b", re.I)),
    ("concurrency", "concurrency, request coalescing, duplicate concurrent generation",
     re.compile(r"\bpending\w*\s*=|in-?flight|await\s+Promise\.all", re.I)),
    ("process_local_state", "process-local mutable state, horizontal scalability",
     re.compile(r"^\s*(let|const|var)\s+\w+\s*=\s*(\{\}|\[\]|null)\s*;?\s*$", re.MULTILINE)),
    ("auth", "authentication, authorization, session/token handling",
     re.compile(r"\b(jwt|authorization|req\.user|session)\b", re.I)),
    ("database_query", "database consistency, data integrity, query correctness",
     re.compile(r"\.find(One|ById)?\(|\.aggregate\(|\bSELECT\b|\.query\(|\.execute\(")),
    ("unbounded_query", "resource bounds, pagination, unbounded payload",
     re.compile(r"\.find\(\{\}\)|\.find\(\)")),
    ("regex_construction", "regex built from user-controlled input",
     re.compile(r"new RegExp\(|RegExp\(")),
    ("date_parsing", "date validation, date handling",
     re.compile(r"\bnew Date\(|Date\.parse\(")),
    ("numeric_conversion", "numeric conversion, finite-number validation",
     re.compile(r"\bNumber\(|parseInt\(|parseFloat\(")),
    ("aggregation", "aggregation logic, correctness",
     re.compile(r"\.reduce\(|\.aggregate\(")),
]

# Always-eligible baseline domains -- almost any snippet can legitimately cite
# validation/correctness standards, so these aren't gated behind a signal
# match the way the AI-boundary/caching/concurrency ones above are.
_BASELINE_DOMAINS = "validation of supplied values, error handling, correctness"


def _extract_whole_file_signals(code: str) -> tuple[list[str], list[str]]:
    """Scans the FULL source once and returns (domain_hints, evidence_lines)
    for every signal pattern that matched anywhere in the file -- not just in
    a truncated prefix. evidence_lines holds one representative line per
    matched signal, in source order of first match."""
    lines = (code or "").splitlines()
    domain_hints: list[str] = []
    evidence_lines: list[str] = []
    for _key, domain_hint, pattern in _SIGNAL_PATTERNS:
        match = pattern.search(code or "")
        if not match:
            continue
        domain_hints.append(domain_hint)
        line_no = code.count("\n", 0, match.start())
        line_text = lines[line_no].strip() if 0 <= line_no < len(lines) else match.group(0)
        evidence_lines.append(line_text[:160])
    return domain_hints, evidence_lines


def build_paste_knowledge_query(code: str, language: str, deterministic_findings: list[Issue]) -> str:
    """Pre-review query: built from deterministic findings + signals detected
    across the WHOLE snippet (not a truncated prefix), used to retrieve a
    small set of standards BEFORE the AI quality review runs, so the reviewer
    knows what engineering risks to look for instead of only decorating
    findings after the fact (see attach_issue_knowledge, which runs post-hoc
    per finding — this is the pre-review counterpart)."""
    finding_terms = "\n".join(
        f"- {issue.category}: {issue.issue} line {issue.line}" for issue in deterministic_findings[:5]
    )
    domain_hints, evidence_lines = _extract_whole_file_signals(code)
    domains = ", ".join([_BASELINE_DOMAINS] + domain_hints)
    evidence_block = "\n".join(f"- {line}" for line in evidence_lines) or "(no strong signal matched; see code excerpt below)"

    parts = [
        f"PASTE CODE REVIEW LANGUAGE: {language}",
        f"Retrieve standards that match the concrete code behavior below, across these domains actually present in the snippet: {domains}.",
        f"Deterministic findings:\n{finding_terms or '(none)'}",
        "Representative evidence lines from across the whole snippet:",
        evidence_block,
    ]
    if not domain_hints:
        # No structural signal matched at all (e.g. a tiny/simple snippet) --
        # fall back to a short raw excerpt so the query isn't just headers.
        compact_code = "\n".join(line.strip() for line in (code or "").splitlines() if line.strip())
        parts.append("Code evidence excerpt:")
        parts.append(compact_code)
    return redact_sensitive_query_text("\n".join(parts), max_chars=1400)


def build_issue_knowledge_query(issue: Issue, code: str, language: str) -> str:
    lines = (code or "").splitlines()
    line_no = max(1, issue.line or 1)
    start = max(0, line_no - 3)
    end = min(len(lines), line_no + 2)
    context = "\n".join(lines[start:end])
    return redact_sensitive_query_text(
        "\n".join(
            [
                f"PASTE FINDING LANGUAGE: {language}",
                f"TITLE: {issue.issue}",
                f"RULE: {issue.rule or issue.category}",
                f"CATEGORY: {issue.category}",
                f"LINE: {issue.line}",
                f"EVIDENCE: {issue.evidence}",
                f"REASON: {issue.fix_suggestion}",
                "LOCAL CODE CONTEXT:",
                context,
            ]
        ),
        max_chars=1000,
    )


def _knowledge_for_client(knowledge: dict | None) -> dict:
    if not knowledge:
        return {
            "mode": "unavailable",
            "available": False,
            "records": [],
            "record_count": 0,
        }
    records = []
    for record in knowledge.get("records", []):
        records.append(
            {
                "knowledge_id": record.get("knowledge_id") or record.get("rule_id"),
                "rule_id": record.get("rule_id") or record.get("knowledge_id"),
                "title": record.get("title"),
                "category": record.get("category"),
                "subcategory": record.get("subcategory"),
                "retrieval_method": record.get("retrieval_method"),
                "relevance_reason": record.get("relevance_reason"),
                "relevance_score": record.get("relevance_score"),
            }
        )
    return {
        "mode": knowledge.get("mode"),
        "available": knowledge.get("available"),
        "reason": knowledge.get("reason"),
        "records": records,
        "record_count": len(records),
        "seed_record_count": knowledge.get("seed_record_count"),
        "indexed_record_count": knowledge.get("indexed_record_count"),
        "vector_record_count": knowledge.get("vector_record_count"),
        "reranked_for_paste": knowledge.get("reranked_for_paste"),
    }


# Own paste-review-specific stopwords, unioned with knowledge/retrieval.py's
# _GENERIC_QUERY_WORDS (reused rather than duplicated -- "api"/"request"/
# "data"/"value" etc. are common enough across unrelated KB record titles
# that sharing them proves nothing about topical relevance; this was
# previously a much narrower local list that let e.g. a CORS record and a
# pagination record falsely "overlap" a finding via generic words alone).
_PASTE_STOPWORDS = _GENERIC_QUERY_WORDS | {
    "the", "and", "for", "with", "that", "this", "from", "code", "review", "match",
    "concrete", "behavior", "language", "javascript", "python", "typescript",
    "function", "return", "const", "let", "else", "current", "previous",
}


def _paste_tokens(text: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", text or ""):
        lowered = token.lower()
        if lowered in _PASTE_STOPWORDS:
            continue
        if len(lowered) > 4 and lowered.endswith("s"):
            lowered = lowered[:-1]
        tokens.add(lowered)
    return tokens


def _record_overlap_score(record: dict, evidence_tokens: set[str]) -> int:
    record_text = " ".join(
        str(record.get(field) or "")
        for field in ("rule_id", "title", "category", "subcategory", "description", "why_it_matters")
    )
    return len(_paste_tokens(record_text) & evidence_tokens)


def _record_from_seed(rule_id: str, retrieval_method: str, reason: str) -> dict | None:
    for record in KNOWLEDGE_RECORDS:
        if record.rule_id == rule_id:
            doc = record.model_dump(exclude={"embedding"})
            doc["knowledge_id"] = record.rule_id
            doc["retrieval_method"] = retrieval_method
            doc["relevance_reason"] = reason
            doc["relevance_score"] = None
            return doc
    return None


def _seed_matches_for_issue(issue: Issue) -> list[dict]:
    text = f"{issue.rule} {issue.issue} {issue.evidence} {issue.fix_suggestion}".lower()
    candidates = []
    if issue.rule and _record_from_seed(issue.rule, "curated_evidence_match", "Exact detector standard for this finding"):
        candidates.append((issue.rule, "Exact detector standard for this finding"))
        if issue.rule == "js_date_slice_without_validation":
            candidates.append(("API-GEN-001", "Finding evidence uses supplied values without visible validation"))
    elif any(token in text for token in (".slice(", ".substring(", ".substr(")) and "date" in text:
        # Only inject the slicing-specific standard when the evidence actually
        # shows a slice/substring call, not merely the word "date" — a plain
        # date-validation finding with no slicing operation should not be
        # matched against a standard about validating before slicing.
        candidates.append(("js_date_slice_without_validation", "Finding evidence shows a slice/substring call on a date-like value"))
        if any(token in text for token in ("input", "validation", "supplied", "transaction", "malformed")):
            candidates.append(("API-GEN-001", "Finding evidence uses supplied values without visible validation"))
    else:
        if any(token in text for token in ("zero", "baseline", "previous", "percentage", "division")):
            candidates.append(("js_zero_baseline_fallback", "Finding evidence is a numeric zero-boundary calculation"))
        if any(token in text for token in ("number(", "numeric", "amount", "coerc", "nan")):
            candidates.append(("js_numeric_coercion_default", "Finding evidence is numeric conversion/defaulting"))
        if any(token in text for token in ("input", "validation", "supplied", "transaction", "malformed")):
            candidates.append(("API-GEN-001", "Finding evidence uses supplied values without visible validation"))

    docs = []
    seen = set()
    for rule_id, reason in candidates:
        if rule_id in seen:
            continue
        doc = _record_from_seed(rule_id, "curated_evidence_match", reason)
        if doc:
            docs.append(doc)
            seen.add(rule_id)
    return docs


def _knowledge_records_for_issue_client(knowledge: dict | None) -> list[dict]:
    records = []
    for record in (knowledge or {}).get("records", []):
        records.append(
            {
                "knowledge_id": record.get("knowledge_id") or record.get("rule_id"),
                "rule_id": record.get("rule_id") or record.get("knowledge_id"),
                "title": record.get("title"),
                "category": record.get("category"),
                "subcategory": record.get("subcategory"),
            }
        )
    return records


# Maps an Issue.category to the KB categories worth considering for it. Not
# a strict 1:1 mapping -- an issue category can plausibly relate to more than
# one KB category (e.g. a reliability issue is often also an architecture
# concern). "correctness" and "api_design" are always eligible since almost
# any finding can cite a validation/correctness standard.
_ISSUE_TO_KB_CATEGORIES = {
    "security": {"security"},
    "performance": {"performance"},
    "logic": {"correctness"},
    "correctness": {"correctness"},
    "reliability": {"reliability", "architecture"},
    "database": {"database", "data_integrity"},
    "data_integrity": {"data_integrity", "database"},
    "api_design": {"api_design"},
    "architecture": {"architecture", "reliability"},
    "privacy": {"privacy", "security"},
    "maintainability": {"maintainability"},
    "production_readiness": {"production_readiness", "reliability"},
    "best_practice": set(),
    "style": set(),
}


def _framework_mismatch(record: dict, evidence_tokens: set[str]) -> bool:
    """A KB record scoped to a specific framework (e.g. framework=["react"])
    must not attach to a finding unless that framework is actually evidenced
    -- callers here never pass a `frameworks` filter to retrieve_knowledge (no
    framework is detected for a pasted snippet), so that scoping would
    otherwise be completely inert and e.g. a React bundle-splitting record
    could attach to a plain Express backend finding just by both being
    javascript. "any" is always eligible."""
    frameworks = [f for f in (record.get("framework") or []) if f and f != "any"]
    if not frameworks:
        return False
    return not any(fw.lower() in evidence_tokens for fw in frameworks)


def _requires_slicing_evidence_but_lacks_it(rule_id: str, evidence_lower: str) -> bool:
    """js_date_slice_without_validation is specifically about a slice/
    substring call on a date-like value -- it should never attach (whether
    surfaced via curated match or semantic search) unless the finding's own
    evidence shows one. Otherwise a merely date-adjacent finding gets
    technique-specific guidance that doesn't apply to it."""
    if rule_id != "js_date_slice_without_validation":
        return False
    return not any(token in evidence_lower for token in (".slice(", ".substring(", ".substr("))


def rerank_issue_knowledge(knowledge: dict, issue: Issue, query: str, top_k: int = 3) -> dict:
    evidence_tokens = _paste_tokens(query)
    evidence_lower = (issue.evidence or "").lower()
    selected = []
    seen = set()
    # No blanket "correctness/api_design are always eligible" bias -- a
    # finding's own category is the sole source of which KB domains are
    # relevant to it (Phase 5: this blanket was why an api_design-tagged
    # pagination record could attach to an unrelated fail-open rate-limiter
    # finding just by both existing).
    allowed_categories = _ISSUE_TO_KB_CATEGORIES.get(issue.category, set())

    for doc in _seed_matches_for_issue(issue):
        if (doc.get("category") or "") not in allowed_categories:
            continue
        key = doc.get("rule_id")
        if key not in seen and not _requires_slicing_evidence_but_lacks_it(key, evidence_lower):
            selected.append(doc)
            seen.add(key)

    for record in knowledge.get("records", []):
        key = record.get("knowledge_id") or record.get("rule_id")
        if not key or key in seen:
            continue
        if (record.get("category") or "") not in allowed_categories:
            continue
        if _requires_slicing_evidence_but_lacks_it(key, evidence_lower):
            continue
        if _framework_mismatch(record, evidence_tokens):
            continue
        score = _record_overlap_score(record, evidence_tokens)
        # No title-keyword bypass: a record whose title merely contains a
        # common word like "validation" or "input" is not thereby relevant
        # to THIS finding -- relevance must be earned via real token overlap
        # with the finding's own evidence/category, every time, no exceptions.
        if score < 2:
            continue
        selected.append(record)
        seen.add(key)
        if len(selected) >= top_k:
            break

    reranked = dict(knowledge)
    reranked["records"] = selected[:top_k]
    reranked["reranked_for_paste_finding"] = True
    reranked["vector_record_count"] = len(knowledge.get("records", []))
    return reranked


def _issue_tokens(issue: Issue) -> set[str]:
    return _paste_tokens(f"{issue.issue} {issue.evidence} {issue.fix_suggestion}")


def dedupe_quality_against_deterministic(quality: list[Issue], deterministic: list[Issue]) -> list[Issue]:
    kept = []
    deterministic_by_line = {}
    for issue in deterministic:
        deterministic_by_line.setdefault(issue.line, []).append(_issue_tokens(issue))

    for issue in quality:
        tokens = _issue_tokens(issue)
        duplicates = any(len(tokens & existing) >= 2 for existing in deterministic_by_line.get(issue.line, []))
        if not duplicates:
            kept.append(issue)
    return kept


_SEVERITY_RANK = {"low": 0, "medium": 1, "critical": 2}
_IDENTIFIER_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{4,}")


def _issue_theme_tokens(issue: Issue) -> set[str]:
    return _paste_tokens(f"{issue.issue} {issue.category}")


def _issue_identifiers(issue: Issue) -> set[str]:
    """snake_case/camelCase-shaped identifiers (5+ chars) mentioned in the
    finding. Two findings about the same variable/field (e.g. document_type)
    are strong dedup evidence even when the surrounding prose differs enough
    that plain theme-token overlap alone wouldn't clear a ratio threshold."""
    text = f"{issue.issue} {issue.evidence}"
    return {
        tok.lower() for tok in _IDENTIFIER_RE.findall(text)
        if "_" in tok or re.search(r"[a-z][A-Z]", tok)
    }


def dedupe_ai_findings(issues: list[Issue]) -> list[Issue]:
    """Phase 9: AI-vs-AI semantic dedup. The model can describe the same root
    cause twice in one response under different wording (observed: "unsupported
    document_type can cause KeyError" and "document_type is not validated
    against known template keys" for the same line) -- merge those instead of
    surfacing both. Two candidates merge only when they're close in the file
    AND (share a real code identifier the finding is about, e.g. document_type
    -- the strongest signal two findings are about the same root cause -- OR
    share enough general theme-token overlap); a shared line alone is not
    enough (two genuinely distinct risks can legitimately sit on one line)."""
    merged: list[Issue] = []
    for issue in issues:
        theme = _issue_theme_tokens(issue)
        identifiers = _issue_identifiers(issue)
        match_index = None
        for index, existing in enumerate(merged):
            if abs((existing.line or 0) - (issue.line or 0)) > 5:
                continue
            shared_identifier = bool(identifiers & _issue_identifiers(existing))
            existing_theme = _issue_theme_tokens(existing)
            overlap = len(theme & existing_theme) if theme and existing_theme else 0
            smaller = min(len(theme), len(existing_theme)) or 1
            strong_theme_overlap = overlap >= 2 and overlap / smaller >= 0.5
            if shared_identifier or strong_theme_overlap:
                match_index = index
                break
        if match_index is None:
            merged.append(issue)
            continue
        existing = merged[match_index]
        # Prefer higher severity, then higher confidence, then the more
        # substantively supported candidate (longer evidence + fix).
        merged[match_index] = max(
            (existing, issue),
            key=lambda i: (
                _SEVERITY_RANK.get(i.severity, 0),
                i.confidence,
                len(i.evidence or "") + len(i.fix_suggestion or ""),
            ),
        )
    return merged


def drop_low_value_style_noise(issues: list[Issue]) -> list[Issue]:
    """Phase 10: style analysis itself isn't disabled (deterministic style
    rules and a confident/severe style finding both still surface) -- only a
    low-severity, low-confidence cosmetic finding (e.g. "docstring has an
    extraneous leading quote") is held back from the default review so it
    doesn't compete for attention with security/reliability findings."""
    return [
        issue for issue in issues
        if not (issue.category == "style" and issue.severity == "low" and issue.confidence < 0.6)
    ]


async def attach_issue_knowledge(issues: list[Issue], code: str, language: str, top_k: int = 3) -> list[Issue]:
    for index, issue in enumerate(issues):
        query = build_issue_knowledge_query(issue, code, language)
        try:
            knowledge = await retrieve_knowledge(
                query,
                language=language,
                top_k=8,
                exact_rule_id=issue.rule or None,
                include_exact=True,
            )
            knowledge = rerank_issue_knowledge(knowledge, issue, query, top_k=top_k)
            records = knowledge.get("records", [])
            issue.knowledge_standards = _knowledge_records_for_issue_client(knowledge)
            print(
                "[review] finding knowledge "
                f"finding={index}:{issue.rule or issue.category}:{issue.line} "
                f"top_k={top_k} ids={[r.get('rule_id') for r in records]} "
                f"methods={[r.get('retrieval_method') for r in records]} "
                f"scores={[round(r.get('score'), 3) for r in records if isinstance(r.get('score'), (int, float))]}"
            )
        except Exception as exc:
            print(f"[review] finding knowledge retrieval failed finding={index}: {type(exc).__name__}")
            issue.knowledge_standards = []
    return issues


def rerank_paste_knowledge(knowledge: dict, query: str, code: str, top_k: int = 4) -> dict:
    """Phase 5/7: a single explainable relevance gate -- real lexical token
    overlap with the snippet's own evidence -- instead of the previous mix of
    ad hoc per-title/per-category string blockers (which only ever covered
    the specific bad matches someone had already noticed) plus an unconditional
    curated-record injection triggered by generic tokens like "amount"/"date"/
    "type"/"transaction" appearing ANYWHERE in the snippet, regardless of
    whether any actual finding supported that standard. Exact/curated matches
    (retrieval_method != "semantic") already proved relevance upstream and
    skip the lexical gate; semantic matches must earn real evidence overlap."""
    evidence_tokens = _paste_tokens(query + "\n" + code)
    selected = []
    seen = set()

    for record in knowledge.get("records", []):
        key = record.get("knowledge_id") or record.get("rule_id")
        if not key or key in seen:
            continue
        if (record.get("retrieval_method") or "") == "exact_rule":
            # Already proved relevant via a deterministic title/phrase-overlap
            # match upstream (knowledge/retrieval.py's _exact_records) -- no
            # second lexical gate needed.
            selected.append(record)
            seen.add(key)
        elif not _framework_mismatch(record, evidence_tokens):
            # "semantic" (cosine-only, can still be topically-adjacent-but-
            # irrelevant) and "deterministic_fallback" (no relevance signal
            # at all, just same language/category) both need real overlap.
            score = _record_overlap_score(record, evidence_tokens)
            if score < 2:
                continue
            selected.append(record)
            seen.add(key)
        if len(selected) >= top_k:
            break

    reranked = dict(knowledge)
    reranked["records"] = selected[:top_k]
    reranked["reranked_for_paste"] = True
    reranked["vector_record_count"] = len(knowledge.get("records", []))
    return reranked


@router.post("/review", response_model=ReviewResponse)
async def review(payload: ReviewRequestIn, current_user: dict = Depends(get_current_user)):
    tracer = StageTracer("paste_review")
    try:
        language_detection = detect_language(payload.code, payload.language)
        effective_language = language_detection["effective"]
        with tracer.stage("deterministic_ms"):
            deterministic = _deterministic_review_response(payload.code, effective_language)
        deterministic_issues = deterministic.deterministic_findings
        tracer.count("deterministic_findings", len(deterministic_issues))

        # Pre-review RAG: retrieve a small set of relevant standards BEFORE the
        # AI review runs, so the model knows what to check for instead of RAG
        # only decorating findings after they already exist (attach_issue_knowledge
        # below is the post-hoc, per-finding counterpart to this).
        pre_review_knowledge = None
        knowledge_queries = 0
        with tracer.stage("pre_rag_ms"):
            try:
                pre_review_query = build_paste_knowledge_query(payload.code, effective_language, deterministic_issues)
                pre_review_knowledge = await retrieve_knowledge(pre_review_query, language=effective_language, top_k=6)
                knowledge_queries += 1
                pre_review_knowledge = rerank_paste_knowledge(pre_review_knowledge, pre_review_query, payload.code, top_k=4)
            except Exception as exc:
                print(f"[review] pre-review knowledge retrieval failed, continuing without it: {type(exc).__name__}")
                pre_review_knowledge = None
        tracer.count("pre_rag_records", len((pre_review_knowledge or {}).get("records", [])))

        messages = [
            {"role": "user", "content": build_quality_review_prompt(payload.code, effective_language, pre_review_knowledge)}
        ]
        parsed = None
        groq_calls = 0
        try:
            with tracer.stage("groq_ms"):
                raw = await call_groq(messages)
                groq_calls += 1
                parsed = _extract_json(raw)

                if parsed is None:
                    raw = await call_groq(messages)  # retry once
                    groq_calls += 1
                    parsed = _extract_json(raw)

                if parsed is None:
                    raw = await call_groq(messages)  # rotate key, retry again
                    groq_calls += 1
                    parsed = _extract_json(raw)
        except GroqUnavailableError:
            tracer.count("groq_calls", groq_calls)
            with tracer.stage("finding_rag_ms"):
                deterministic_issues = await attach_issue_knowledge(deterministic_issues, payload.code, effective_language)
            response = ReviewResponse(
                issues=deterministic_issues,
                deterministic_findings=deterministic_issues,
                ai_quality_review=[],
                language_detection=language_detection,
                summary=deterministic.summary + "; AI quality review unavailable (model service)",
            )
            try:
                await save_review(
                    payload.code,
                    effective_language,
                    [issue.model_dump() for issue in response.issues],
                    response.summary,
                    current_user["_id"],
                )
            except Exception as exc:
                print(f"[review] failed to save deterministic review to mongo: {exc}")
            tracer.count("ai_candidates", 0)
            tracer.count("grounding_rejected", 0)
            tracer.count("ai_findings_accepted", 0)
            tracer.count("final_findings", len(response.issues))
            tracer.log()
            return response

        if parsed is None:
            tracer.count("groq_calls", groq_calls)
            with tracer.stage("finding_rag_ms"):
                deterministic_issues = await attach_issue_knowledge(deterministic_issues, payload.code, effective_language)
            response = ReviewResponse(
                issues=deterministic_issues,
                deterministic_findings=deterministic_issues,
                ai_quality_review=[],
                language_detection=language_detection,
                summary=deterministic.summary + "; AI quality review unavailable (malformed model response)",
            )
            tracer.count("ai_candidates", 0)
            tracer.count("grounding_rejected", 0)
            tracer.count("ai_findings_accepted", 0)
            tracer.count("final_findings", len(response.issues))
            tracer.log()
            return response

        tracer.count("groq_calls", groq_calls)
        quality_issues, quality_summary = _build_quality_issues(parsed)
        candidate_count = len(quality_issues)
        tracer.count("ai_candidates", candidate_count)
        # P0: mechanical source grounding. An AI candidate must not reach the
        # user just because its JSON parsed — verify its evidence and claimed
        # line actually exist in the source before accepting it.
        with tracer.stage("grounding_ms"):
            quality_issues, rejected = ground_issues(quality_issues, payload.code)
        tracer.count("grounding_rejected", len(rejected))
        if rejected:
            print(f"[review] grounding rejected {len(rejected)}/{candidate_count} AI candidate(s): {rejected}")
        pre_dedup_count = len(quality_issues)
        quality_issues = dedupe_ai_findings(quality_issues)
        tracer.count("ai_ai_duplicates_merged", pre_dedup_count - len(quality_issues))
        quality_issues = drop_low_value_style_noise(quality_issues)
        quality_issues = dedupe_quality_against_deterministic(quality_issues, deterministic_issues)
        tracer.count("ai_findings_accepted", len(quality_issues))
        with tracer.stage("finding_rag_ms"):
            deterministic_issues = await attach_issue_knowledge(deterministic_issues, payload.code, effective_language)
            quality_issues = await attach_issue_knowledge(quality_issues, payload.code, effective_language)
            knowledge_queries += len(deterministic_issues) + len(quality_issues)
        tracer.count("knowledge_queries", knowledge_queries)
        response = ReviewResponse(
            issues=deterministic_issues + quality_issues,
            deterministic_findings=deterministic_issues,
            ai_quality_review=quality_issues,
            language_detection=language_detection,
            summary=(
                f"{len(deterministic_issues)} deterministic finding(s); "
                f"{len(quality_issues)} AI quality finding(s). {quality_summary}"
            ).strip(),
        )
        _apply_confidence_sanity_checks(response)
        tracer.count("final_findings", len(response.issues))

        try:
            await save_review(
                payload.code,
                effective_language,
                [issue.model_dump() for issue in response.issues],
                response.summary,
                current_user["_id"],
            )
        except Exception as exc:
            print(f"[review] failed to save review to mongo: {exc}")

        tracer.log()
        return response
    except Exception as exc:
        tracer.log()
        print(f"[review] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=ERROR_RESPONSE)


@router.post("/review/fix", response_model=FindingTransform)
async def fix_paste_issue(payload: PasteFixRequest, current_user: dict = Depends(get_current_user)):
    try:
        issue = dict(payload.issue or {})
        finding = {
            "rule": issue.get("rule") or issue.get("category") or "paste_quality_issue",
            "severity": issue.get("severity", "medium"),
            "category": issue.get("category", "best_practice"),
            "message": issue.get("issue", ""),
            "evidence": issue.get("evidence", ""),
            "file": "fixed-code",
            "line": issue.get("line", 0),
        }
        prompt = build_transform_prompt(finding, payload.code, payload.language)
        parsed = None
        try:
            raw = await call_groq([{"role": "user", "content": prompt}])
            parsed = _extract_json(raw)
            if parsed is None:
                raw = await call_groq([{"role": "user", "content": prompt}])
                parsed = _extract_json(raw)
        except GroqUnavailableError:
            parsed = None

        if parsed is None:
            return JSONResponse(status_code=500, content=FIX_ERROR_RESPONSE)
        return _build_transform_response(parsed, issue, payload.code)
    except Exception as exc:
        print(f"[review] paste fix error: {exc}")
        return JSONResponse(status_code=500, content=FIX_ERROR_RESPONSE)


@router.get("/reviews/history")
async def history(current_user: dict = Depends(get_current_user)):
    try:
        return await get_history(current_user["_id"])
    except Exception as exc:
        print(f"[history] unhandled error: {exc}")
        return JSONResponse(
            status_code=500, content={"error": "Could not load history, please retry"}
        )
