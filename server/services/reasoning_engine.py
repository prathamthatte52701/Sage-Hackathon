"""The ONLY module that talks to the LLM for finding-level reasoning, fix
generation, and codebase-chat answering. Route handlers call into this —
they never call call_groq() directly. This keeps the boundary between "what
did static analysis determine" (services/analyzers/, services/analyzers/rules.py)
and "what does the AI judge/explain/generate" (this file) enforced by the
code structure, not just convention.
"""

import json
import re

from models.schemas import FindingReasoning, FindingTransform
from services.groq_client import GroqUnavailableError, call_groq
from services.prompt_builder import build_chat_prompt, build_finding_reasoning_prompt, build_transform_prompt


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


def _build_finding_reasoning(raw: dict) -> FindingReasoning:
    """Coerce/drop bad-typed fields instead of crashing, same pattern as _build_issue."""
    data = dict(raw) if isinstance(raw, dict) else {}

    if not isinstance(data.get("findingConfirmed"), bool):
        data.pop("findingConfirmed", None)

    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        data.pop("confidence", None)

    for field in ("severity", "reasoning", "impact", "recommendation", "suggestedFix"):
        if field in data and not isinstance(data[field], str):
            data.pop(field, None)

    if data.get("severity") not in ("critical", "high", "medium", "low"):
        data.pop("severity", None)

    return FindingReasoning(**{k: v for k, v in data.items() if k in FindingReasoning.model_fields})


def _build_finding_transform(raw: dict) -> FindingTransform:
    """Coerce/drop bad-typed fields instead of crashing, same pattern as _build_finding_reasoning."""
    data = dict(raw) if isinstance(raw, dict) else {}

    for field in ("original_snippet", "proposed_fix", "explanation"):
        if field in data and not isinstance(data[field], str):
            data.pop(field, None)

    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        data.pop("confidence", None)

    return FindingTransform(**{k: v for k, v in data.items() if k in FindingTransform.model_fields})


def _build_chat_answer(raw: dict, retrieved_paths: set[str]) -> dict:
    """Coerce/drop bad-typed fields; clamp cited_files to files actually retrieved
    so the AI can't cite a file it was never shown."""
    data = dict(raw) if isinstance(raw, dict) else {}

    answer = data.get("answer")
    if not isinstance(answer, str) or not answer:
        answer = "No answer was returned."

    cited = data.get("cited_files")
    if not isinstance(cited, list):
        cited = []
    cited_files = [c for c in cited if isinstance(c, str) and c in retrieved_paths]

    return {"answer": answer, "cited_files": cited_files}


async def _call_with_retry(prompt: str) -> dict | None:
    """Shared call+parse+one-retry-on-bad-JSON pattern used by every reasoning call."""
    messages = [{"role": "user", "content": prompt}]
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
        raw = await call_groq(retry_messages)
        parsed = _extract_json(raw)

    return parsed


async def confirm_and_explain_finding(
    finding: dict, code_context: str, language: str, standards: list[dict]
) -> FindingReasoning:
    """Takes a deterministic finding + relevant code + the standard(s) it maps
    to. Returns AI's confirm/explain/recommend judgment. Never invents a
    finding — always operates on a finding that already exists."""
    prompt = build_finding_reasoning_prompt(finding, code_context, language, standards)

    result = FindingReasoning()
    try:
        parsed = await _call_with_retry(prompt)
        if parsed is not None:
            result = _build_finding_reasoning(parsed)
            result.citedStandards = [
                {"id": s["id"], "title": s["title"], "evidenceSource": s["evidenceSource"]}
                for s in standards
            ]
    except GroqUnavailableError:
        result = FindingReasoning()

    return result


async def generate_fix(finding: dict, code_context: str, language: str, standards: list[dict]) -> FindingTransform:
    prompt = build_transform_prompt(finding, code_context, language, standards)

    result = FindingTransform()
    try:
        parsed = await _call_with_retry(prompt)
        if parsed is not None:
            result = _build_finding_transform(parsed)
    except GroqUnavailableError:
        result = FindingTransform()

    return result


async def answer_project_question(question: str, retrieved_context: list[dict]) -> dict:
    """Used by codebase chat. Takes ALREADY-RETRIEVED context (services/retrieval.py)
    — this function never decides what's relevant, retrieval already did that.
    This function only reasons over what it's handed."""
    retrieved_paths = {f["path"] for f in retrieved_context}
    prompt = build_chat_prompt(question, retrieved_context)

    result = {
        "answer": "AI answer unavailable — the model service could not be reached.",
        "cited_files": [],
    }
    try:
        parsed = await _call_with_retry(prompt)
        if parsed is not None:
            result = _build_chat_answer(parsed, retrieved_paths)
    except GroqUnavailableError:
        pass

    return result
