import json
import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db.mongo import get_history, save_review
from models.schemas import Issue, ReviewRequest, ReviewResponse
from services.groq_client import GroqUnavailableError, call_groq
from services.analyzers.rules import run_rules
from services.prompt_builder import build_review_prompt

router = APIRouter()

ERROR_RESPONSE = {"error": "Could not analyze this code, please try again"}


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
    return ReviewResponse(issues=issues, summary=summary)


@router.post("/review", response_model=ReviewResponse)
async def review(payload: ReviewRequestIn):
    try:
        messages = [{"role": "user", "content": build_review_prompt(payload.code, payload.language)}]

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
            response = _deterministic_review_response(payload.code, payload.language, "model service")
            try:
                await save_review(
                    payload.code,
                    payload.language,
                    [issue.model_dump() for issue in response.issues],
                    response.summary,
                    payload.session_id,
                )
            except Exception as exc:
                print(f"[review] failed to save deterministic review to mongo: {exc}")
            return response

        if parsed is None:
            response = _deterministic_review_response(payload.code, payload.language, "malformed model response")
            return response

        response = _build_review_response(parsed)
        _apply_confidence_sanity_checks(response)

        try:
            await save_review(
                payload.code,
                payload.language,
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


@router.get("/reviews/history")
async def history(session_id: str):
    try:
        return await get_history(session_id)
    except Exception as exc:
        print(f"[history] unhandled error: {exc}")
        return JSONResponse(
            status_code=500, content={"error": "Could not load history, please retry"}
        )
