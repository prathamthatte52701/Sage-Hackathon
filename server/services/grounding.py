"""Phase 6 (P0): mechanical source grounding for AI-generated findings.

An AI candidate finding must not be accepted merely because its JSON schema
validated. Before a finding reaches the user, verify -- mechanically, not by
asking a second LLM -- that its claimed evidence actually exists in the
source it claims to be about. This is what stops an AI candidate from citing
"overshootCategory" when the source only contains "overspendCategory".

Two checks, in order:
1. line_start (Issue.line) must be within the source's line range, if given.
2. evidence must exist in the source, either as a near-exact substring
   (whitespace-normalized, to tolerate reformatting) or, failing that, as a
   token-level check that its identifiers actually appear somewhere in the
   source. A wholesale token mismatch (an evidence quote built mostly from
   names that don't exist anywhere in the file) is the hallucination
   signature this exists to catch.

Deliberately NOT checked against the source: Issue.missing_control,
Issue.fix_suggestion, Issue.issue. A finding about something ABSENT (no
timeout, no cache invalidation, no concurrency guard) legitimately names an
identifier that will never appear in the source -- that's the whole point of
the finding. The schema (see build_quality_review_prompt) asks the model to
put what actually exists in "evidence" and what's missing in
"missing_control" precisely so this mechanical check only ever verifies the
"exists" half, never penalizing a finding for correctly describing an
absence.
"""

import re

_WORD_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{2,}")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text or "").strip().lower()


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text or "")}


def _identifier_like_tokens(text: str) -> set[str]:
    """Tokens that look like actual code identifiers (camelCase or
    snake_case, 5+ chars) rather than ordinary English prose -- this is
    deliberately narrower than "every uncommon word" so an AI paraphrasing
    a finding in plain English isn't penalized for using a word that simply
    isn't in the source. A fabricated *identifier* (variable/function name)
    is the actual hallucination shape this guards against."""
    result = set()
    for tok in _WORD_RE.findall(text or ""):
        if len(tok) < 5:
            continue
        if "_" in tok or re.search(r"[a-z][A-Z]", tok):
            result.add(tok.lower())
    return result


def ground_issue(issue, code: str) -> tuple[bool, str]:
    """Returns (grounded, rejection_reason). rejection_reason is "" when grounded."""
    lines = (code or "").splitlines()
    line = getattr(issue, "line", None)
    if line and not (1 <= line <= max(len(lines), 1)):
        return False, f"claimed line {line} is outside the source range (source has {len(lines)} lines)"

    evidence = (getattr(issue, "evidence", "") or "").strip()
    if not evidence:
        # No evidence quote to check. Deterministic findings always carry
        # evidence (the rule wouldn't have fired otherwise); an AI candidate
        # missing it entirely can't be mechanically verified, so reject it
        # rather than trust it on the strength of its prose alone.
        if getattr(issue, "source", "") == "ai_quality":
            return False, "no evidence quote provided to ground against source"
        return True, ""

    normalized_source = _normalize(code)
    normalized_evidence = _normalize(evidence)
    if normalized_evidence and normalized_evidence in normalized_source:
        return True, ""

    source_tokens = _tokens(code)

    # Zero tolerance for a fabricated camelCase/snake_case identifier -- this
    # is the exact hallucination shape ("overshootCategory" quoted when the
    # source only has "overspendCategory"): a real-looking name that simply
    # isn't anywhere in the file. Plain English words in the evidence (from
    # an AI paraphrasing rather than quoting verbatim) are not held to this
    # standard -- only identifier-shaped tokens are checked at all.
    missing_identifiers = _identifier_like_tokens(evidence) - source_tokens
    if missing_identifiers:
        return False, f"evidence references identifiers not found anywhere in source: {sorted(missing_identifiers)[:5]}"

    return True, ""


def _reason_code(reason: str) -> str:
    """Phase 13 (dev/trace only, never sent to the client -- see StageTracer's
    docstring): a stable machine-readable bucket for a free-text rejection
    reason, so "why did this snippet produce 0 findings" can be answered by
    counting codes in server logs instead of eyeballing prose every time."""
    if "outside the source range" in reason:
        return "invalid_line"
    if "no evidence quote provided" in reason:
        return "no_source_evidence"
    if "identifiers not found anywhere in source" in reason:
        return "claimed_identifier_missing"
    return "other"


def ground_issues(issues: list, code: str) -> tuple[list, list[dict]]:
    """Filters a list of Issue objects, returning (grounded_issues, rejected).
    `rejected` is a list of {"issue": <short label>, "reason": <str>,
    "reason_code": <str>} for logging/telemetry — never shown to the end user."""
    grounded = []
    rejected = []
    for issue in issues:
        ok, reason = ground_issue(issue, code)
        if ok:
            grounded.append(issue)
        else:
            rejected.append({
                "issue": getattr(issue, "issue", ""),
                "line": getattr(issue, "line", None),
                "reason": reason,
                "reason_code": _reason_code(reason),
            })
    return grounded, rejected
