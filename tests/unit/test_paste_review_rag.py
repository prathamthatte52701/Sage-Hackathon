import json

import pytest

from routers import review as review_router
from routers.review import ReviewRequestIn, detect_language, review


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
        ReviewRequestIn(code=JS_UTILITY, language="python", session_id="test-session")
    )

    assert calls
    assert all(call["language"] == "javascript" for call in calls)
    assert all(call["top_k"] == 8 for call in calls)
    assert any(call["exact_rule_id"] == "js_numeric_coercion_default" for call in calls)
    assert response.language_detection["mismatch"] is True
    deterministic_rules = {issue.issue for issue in response.deterministic_findings}
    assert deterministic_rules
    assert all(issue.category != "security" for issue in response.deterministic_findings)
    assert response.ai_quality_review == []
    assert any(issue.issue.startswith("Invalid numeric") for issue in response.issues)
    returned_ids = {
        record["rule_id"]
        for issue in response.issues
        for record in issue.knowledge_standards
    }
    assert "CORRECT-GEN-001" in returned_ids


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
        ReviewRequestIn(code="export function ok(value) { return value ?? 0; }", language="python", session_id="test-session")
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

    response = await review(ReviewRequestIn(code=code, language="javascript", session_id="test-session"))

    assert response.deterministic_findings == []
    assert len(response.ai_quality_review) == 1
