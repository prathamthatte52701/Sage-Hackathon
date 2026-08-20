import json
import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db.mongo import get_history, save_review
from knowledge.retrieval import redact_sensitive_query_text, retrieve_knowledge
from knowledge.seed_data import KNOWLEDGE_RECORDS
from models.schemas import FindingTransform, Issue, PasteFixRequest, ReviewRequest, ReviewResponse
from services.patching import build_patch_metadata
from services.groq_client import GroqUnavailableError, call_groq
from services.analyzers.rules import run_rules
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


def build_paste_knowledge_query(code: str, language: str, deterministic_findings: list[Issue]) -> str:
    finding_terms = "\n".join(
        f"- {issue.category}: {issue.issue} line {issue.line}" for issue in deterministic_findings[:5]
    )


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
    compact_code = "\n".join(line.strip() for line in (code or "").splitlines() if line.strip())
    return redact_sensitive_query_text(
        "\n".join(
            [
                f"PASTE CODE REVIEW LANGUAGE: {language}",
                "Retrieve standards that match the concrete code behavior below: validation of supplied values, numeric conversion, default branches, date handling, aggregation logic, zero/empty edge cases, error handling, and correctness.",
                f"Deterministic findings:\n{finding_terms or '(none)'}",
                "Code evidence excerpt:",
                compact_code,
            ]
        ),
        max_chars=1400,
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


_PASTE_STOPWORDS = {
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
    elif any(token in text for token in ("date", "slice", "invalid date", "malformed")):
        candidates.append(("js_date_slice_without_validation", "Finding evidence is date parsing/validation related"))
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


def rerank_issue_knowledge(knowledge: dict, issue: Issue, query: str, top_k: int = 3) -> dict:
    evidence_tokens = _paste_tokens(query)
    selected = []
    seen = set()
    allowed_categories = {"correctness", "api_design"}
    if issue.category == "security":
        allowed_categories.add("security")
    if issue.category == "performance":
        allowed_categories.add("performance")

    for doc in _seed_matches_for_issue(issue):
        if (doc.get("category") or "") not in allowed_categories:
            continue
        key = doc.get("rule_id")
        if key not in seen:
            selected.append(doc)
            seen.add(key)

    for record in knowledge.get("records", []):
        key = record.get("knowledge_id") or record.get("rule_id")
        if not key or key in seen:
            continue
        if (record.get("category") or "") not in allowed_categories:
            continue
        score = _record_overlap_score(record, evidence_tokens)
        title = (record.get("title") or "").lower()
        if score < 2 and not any(token in title for token in ("date", "numeric", "zero", "validation", "input")):
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
    evidence_tokens = _paste_tokens(query + "\n" + code)
    selected = []
    seen = set()

    for record in knowledge.get("records", []):
        category = (record.get("category") or "").lower()
        title = (record.get("title") or "").lower()
        if "stack trace" in title and not ({"stack", "trace", "client", "api", "response"} & evidence_tokens):
            continue
        if "api failure" in title and not ({"api", "fetch", "request", "response", "loading", "client"} & evidence_tokens):
            continue
        if category in {"security", "database", "performance"} and not ({"database", "query", "request", "http", "secret", "token"} & evidence_tokens):
            continue
        if "api" in title and not ({"api", "request", "response", "input", "validation", "external", "supplied"} & evidence_tokens):
            continue
        score = _record_overlap_score(record, evidence_tokens)
        if score < 2:
            continue
        key = record.get("knowledge_id") or record.get("rule_id")
        if key and key not in seen:
            selected.append(record)
            seen.add(key)
        if len(selected) >= top_k:
            break

    value_validation_evidence = {"amount", "date", "type", "transaction", "transactions", "value", "validation", "supplied"} & evidence_tokens
    if value_validation_evidence and "API-GEN-001" not in seen:
        validation_record = _record_from_seed(
            "API-GEN-001",
            "curated_evidence_match",
            "Pasted code uses supplied values without visible validation",
        )
        if validation_record:
            selected.insert(0, validation_record)

    reranked = dict(knowledge)
    reranked["records"] = selected[:top_k]
    reranked["reranked_for_paste"] = True
    reranked["vector_record_count"] = len(knowledge.get("records", []))
    return reranked


@router.post("/review", response_model=ReviewResponse)
async def review(payload: ReviewRequestIn):
    try:
        language_detection = detect_language(payload.code, payload.language)
        effective_language = language_detection["effective"]
        deterministic = _deterministic_review_response(payload.code, effective_language)
        deterministic_issues = deterministic.deterministic_findings

        messages = [{"role": "user", "content": build_quality_review_prompt(payload.code, effective_language, None)}]
        parsed = None
        try:
            raw = await call_groq(messages)
            parsed = _extract_json(raw)

            if parsed is None:
                raw = await call_groq(messages)  # retry once
                parsed = _extract_json(raw)

            if parsed is None:
                raw = await call_groq(messages)  # rotate key, retry again
                parsed = _extract_json(raw)
        except GroqUnavailableError:
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
                    payload.session_id,
                )
            except Exception as exc:
                print(f"[review] failed to save deterministic review to mongo: {exc}")
            return response

        if parsed is None:
            deterministic_issues = await attach_issue_knowledge(deterministic_issues, payload.code, effective_language)
            response = ReviewResponse(
                issues=deterministic_issues,
                deterministic_findings=deterministic_issues,
                ai_quality_review=[],
                language_detection=language_detection,
                summary=deterministic.summary + "; AI quality review unavailable (malformed model response)",
            )
            return response

        quality_issues, quality_summary = _build_quality_issues(parsed)
        quality_issues = dedupe_quality_against_deterministic(quality_issues, deterministic_issues)
        deterministic_issues = await attach_issue_knowledge(deterministic_issues, payload.code, effective_language)
        quality_issues = await attach_issue_knowledge(quality_issues, payload.code, effective_language)
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

        try:
            await save_review(
                payload.code,
                effective_language,
                [issue.model_dump() for issue in response.issues],
                response.summary,
                payload.session_id,
            )
        except Exception as exc:
            print(f"[review] failed to save review to mongo: {exc}")

        return response
    except Exception as exc:
        print(f"[review] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=ERROR_RESPONSE)


@router.post("/review/fix", response_model=FindingTransform)
async def fix_paste_issue(payload: PasteFixRequest):
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
async def history(session_id: str):
    try:
        return await get_history(session_id)
    except Exception as exc:
        print(f"[history] unhandled error: {exc}")
        return JSONResponse(
            status_code=500, content={"error": "Could not load history, please retry"}
        )
