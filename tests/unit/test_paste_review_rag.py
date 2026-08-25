import json

import pytest

from models.schemas import Issue
from routers import review as review_router
from routers.review import ReviewRequestIn, detect_language, dedupe_ai_findings, drop_low_value_style_noise, review


JS_UTILITY = """
export function summarizeTransactions(transactions) {
  return transactions.reduce((summary, tx) => {
    const amount = Number(tx.amount) || 0;
    if (tx.type === "credit") {
      summary.income += amount;
    } else {
      summary.expense += amount;
    }
    summary.byDay[tx.date.slice(0, 10)] = amount;
    return summary;
  }, { income: 0, expense: 0, byDay: {} });
}

export function percentageChange(current, previous) {
  if (!previous) return 0;
  return ((current - previous) / previous) * 100;
}
"""


def test_detect_language_switches_obvious_javascript_from_python():
    result = detect_language(JS_UTILITY, "python")

    assert result["mismatch"] is True
    assert result["detected"] == "javascript"
    assert result["effective"] == "javascript"


@pytest.mark.asyncio
async def test_paste_review_calls_knowledge_and_adds_quality_review(monkeypatch):
    calls = []

    async def fake_retrieve(query, language=None, top_k=4, **kwargs):
        calls.append(
            {
                "query": query,
                "language": language,
                "top_k": top_k,
                "include_exact": kwargs.get("include_exact"),
                "exact_rule_id": kwargs.get("exact_rule_id"),
            }
        )
        return {
            "mode": "hybrid",
            "available": True,
            "seed_record_count": 50,
            "indexed_record_count": 50,
            "records": [
                {
                    "knowledge_id": "CORRECT-GEN-001",
                    "rule_id": "CORRECT-GEN-001",
                    "title": "Validate numeric input before calculation",
                    # Phase 5 removed the "title contains a generic bypass
                    # word" shortcut that used to rescue a record with weak
                    # lexical overlap -- this mock now needs genuine overlap
                    # with what a real finding/query about this snippet
                    # would say, same as a real KB record would need.
                    "description": "Numeric values silently coerced to zero without validation are a correctness risk.",
                    "category": "correctness",
                    "retrieval_method": "semantic",
                    "relevance_reason": "Atlas Vector Search semantic match",
                }
            ],
        }

    async def fake_call_groq(messages):
        return json.dumps(
            {
                "issues": [
                    {
                        "line": 4,
                        "severity": "medium",
                        "category": "logic",
                        "issue": "Invalid amounts are silently coerced to zero.",
                        "fix_suggestion": "Validate tx.amount explicitly and reject or report invalid numeric values.",
                        "confidence": 0.82,
                        "evidence": "Number(tx.amount) || 0",
                        "knowledge_ids": ["CORRECT-GEN-001"],
                    }
                ],
                "summary": "One evidence-backed quality concern found.",
            }
        )

    async def fake_save_review(*args, **kwargs):
        return None

    monkeypatch.setattr(review_router, "retrieve_knowledge", fake_retrieve)
    monkeypatch.setattr(review_router, "call_groq", fake_call_groq)
    monkeypatch.setattr(review_router, "save_review", fake_save_review)

    response = await review(
        ReviewRequestIn(code=JS_UTILITY, language="python", session_id="test-session"),
        current_user={"_id": "test-user"},
    )

    assert calls
    assert all(call["language"] == "javascript" for call in calls)
    # Phase 3 fix: a pre-review knowledge call (top_k=6, built from
    # build_paste_knowledge_query) now runs BEFORE the AI review, in addition
    # to the existing per-finding calls (top_k=8) that run after. Previously
    # build_paste_knowledge_query was dead code with no return statement, so
    # this call never happened at all -- RAG only ever decorated findings
    # after the fact instead of informing the review itself.
    pre_review_calls = [c for c in calls if c["query"].startswith("PASTE CODE REVIEW LANGUAGE:")]
    finding_calls = [c for c in calls if c["query"].startswith("PASTE FINDING LANGUAGE:")]
    assert len(pre_review_calls) == 1
    assert pre_review_calls[0]["top_k"] == 6
    assert finding_calls
    assert all(call["top_k"] == 8 for call in finding_calls)
    assert any(call["exact_rule_id"] == "js_numeric_coercion_default" for call in finding_calls)
    assert response.language_detection["mismatch"] is True
    deterministic_rules = {issue.issue for issue in response.deterministic_findings}
    assert deterministic_rules
    assert all(issue.category != "security" for issue in response.deterministic_findings)
    # AI quality review now works and returns findings
    assert response.ai_quality_review != []
    assert len(response.ai_quality_review) >= 1
    assert any("coerced to zero" in issue.issue for issue in response.ai_quality_review)
    assert any(issue.issue.startswith("Invalid numeric") for issue in response.issues)
    returned_ids = {
        record["rule_id"]
        for issue in response.issues
        for record in issue.knowledge_standards
    }
    assert "CORRECT-GEN-001" in returned_ids


def test_dedupe_ai_findings_merges_same_root_cause_different_wording():
    # Mirrors the real OCR test: two candidates on the same line describing
    # the same root cause (unsupported document_type) under different wording.
    a = Issue(
        line=20, category="correctness", severity="medium", confidence=0.7,
        issue="unsupported document_type can cause KeyError",
        evidence="_TEMPLATE_BY_TYPE[document_type]", source="ai_quality",
    )
    b = Issue(
        line=21, category="correctness", severity="critical", confidence=0.6,
        issue="document_type is not validated against known template keys",
        evidence="_env.get_template(_TEMPLATE_BY_TYPE[document_type]).render()", source="ai_quality",
    )
    merged = dedupe_ai_findings([a, b])
    assert len(merged) == 1
    # higher severity of the two candidates wins
    assert merged[0].severity == "critical"


def test_dedupe_ai_findings_keeps_distinct_risks_on_nearby_lines():
    a = Issue(
        line=5, category="security", severity="medium", confidence=0.7,
        issue="Hardcoded API key committed to source",
        evidence="const key = 'sk-abc123';", source="ai_quality",
    )
    b = Issue(
        line=6, category="reliability", severity="medium", confidence=0.7,
        issue="No timeout on the outbound fetch call",
        evidence="await fetch(url)", source="ai_quality",
    )
    merged = dedupe_ai_findings([a, b])
    assert len(merged) == 2


def test_drop_low_value_style_noise_removes_low_confidence_cosmetic_finding():
    cosmetic = Issue(line=1, category="style", severity="low", confidence=0.4, issue="docstring has an extraneous leading quote")
    substantive = Issue(line=2, category="best_practice", severity="low", confidence=0.7, issue="filename is not validated against an extension allowlist")
    kept = drop_low_value_style_noise([cosmetic, substantive])
    assert kept == [substantive]


def test_drop_low_value_style_noise_keeps_confident_or_severe_style_finding():
    confident_style = Issue(line=1, category="style", severity="low", confidence=0.8, issue="inconsistent naming convention obscures a real behavior difference")
    kept = drop_low_value_style_noise([confident_style])
    assert kept == [confident_style]


@pytest.mark.asyncio
async def test_paste_review_falls_back_when_rag_and_model_fail(monkeypatch):
    async def fail_retrieve(*args, **kwargs):
        raise RuntimeError("atlas down")

    async def fail_call_groq(*args, **kwargs):
        raise review_router.GroqUnavailableError("model down")

    async def fake_save_review(*args, **kwargs):
        return None

    monkeypatch.setattr(review_router, "retrieve_knowledge", fail_retrieve)
    monkeypatch.setattr(review_router, "call_groq", fail_call_groq)
    monkeypatch.setattr(review_router, "save_review", fake_save_review)

    response = await review(
        ReviewRequestIn(code="export function ok(value) { return value ?? 0; }", language="python", session_id="test-session"),
        current_user={"_id": "test-user"},
    )

    assert response.language_detection["effective"] == "javascript"
    assert response.ai_quality_review == []
    assert response.issues == []
    assert "AI quality review unavailable" in response.summary


@pytest.mark.asyncio
async def test_zero_deterministic_findings_still_allows_quality_review(monkeypatch):
    code = """
export function fullName(user) {
  return user.firstName.trim() + " " + user.lastName.trim();
}
"""

    async def fake_retrieve(*args, **kwargs):
        return {
            "mode": "hybrid",
            "available": True,
            "records": [
                {
                    "knowledge_id": "API-GEN-001",
                    "rule_id": "API-GEN-001",
                    "title": "Validate external input at API boundaries",
                    "category": "api_design",
                    "retrieval_method": "semantic",
                }
            ],
        }

    async def fake_call_groq(messages):
        return json.dumps(
            {
                "issues": [
                    {
                        "line": 3,
                        "severity": "low",
                        "category": "logic",
                        "issue": "The function assumes user/name fields are present before calling trim.",
                        "fix_suggestion": "Validate user, firstName, and lastName before trimming.",
                        "confidence": 0.8,
                        # Phase 6 grounding requires evidence that actually exists in the
                        # source for an ai_quality finding to be accepted -- this fixture
                        # previously had none, so the (correct) new grounding gate rejected it.
                        "evidence": "user.firstName.trim()",
                    }
                ],
                "summary": "One evidence-backed quality concern found.",
            }
        )

    async def fake_save_review(*args, **kwargs):
        return None

    monkeypatch.setattr(review_router, "retrieve_knowledge", fake_retrieve)
    monkeypatch.setattr(review_router, "call_groq", fake_call_groq)
    monkeypatch.setattr(review_router, "save_review", fake_save_review)

    response = await review(
        ReviewRequestIn(code=code, language="javascript", session_id="test-session"),
        current_user={"_id": "test-user"},
    )

    assert response.deterministic_findings == []
    assert len(response.ai_quality_review) == 1
