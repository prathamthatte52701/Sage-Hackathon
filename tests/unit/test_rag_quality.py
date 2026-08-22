"""Phase 4: RAG relevance quality suite.

Deliberately NOT mocked -- these hit the real configured sage_knowledge
Atlas index via retrieve_knowledge(), because the whole point is to verify
actual retrieval RELEVANCE (real embeddings, real vector search, the real
exact-match heuristic), not just that the function returns something.
If the DB/vector index genuinely isn't reachable in a given environment,
each test skips rather than false-failing on infrastructure absence.
"""

import pytest

from knowledge.retrieval import retrieve_knowledge

# _fresh_db_client_per_test (conftest.py, autouse) resets db.mongo's lazy
# client before every test -- see that fixture's docstring for why.


async def _relevant_records(query: str, top_k: int = 5) -> list[dict]:
    result = await retrieve_knowledge(query, top_k=top_k)
    if result.get("mode") != "hybrid":
        pytest.skip(f"knowledge retrieval unavailable in this environment (mode={result.get('mode')})")
    return result["records"]


def _categories(records: list[dict]) -> set[str]:
    return {r.get("category") for r in records}


def _rule_ids(records: list[dict]) -> set[str]:
    return {r.get("rule_id") for r in records}


@pytest.mark.asyncio
async def test_external_api_timeout_query_returns_relevant_domain():
    records = await _relevant_records("HTTP request to external API has no timeout")
    rule_ids = _rule_ids(records)
    assert "API-GEN-007" in rule_ids or "BG-GEN-001" in rule_ids, (
        f"expected a timeout/retry-reliability standard, got {rule_ids}"
    )
    # must not be dominated by clearly unrelated domains
    assert "SEC-GEN-001" not in rule_ids  # hardcoded secrets
    assert "js_date_slice_without_validation" not in rule_ids  # date slicing


@pytest.mark.asyncio
async def test_month_overflow_query_returns_date_correctness_not_slicing():
    records = await _relevant_records("monthYear accepts month 13 and JavaScript Date normalizes it")
    categories = _categories(records)
    assert categories & {"correctness", "security"}, f"expected a date/input-correctness match, got {categories}"
    # the slicing-specific standard should only appear when slicing evidence
    # exists -- a plain out-of-range-month query has none
    top_rule = records[0].get("rule_id") if records else None
    assert top_rule != "js_date_slice_without_validation", (
        "date-slicing guidance should not be the top match for a non-slicing date query"
    )


@pytest.mark.asyncio
async def test_process_local_auth_cache_query_returns_relevant_domain():
    records = await _relevant_records("authenticated user stored in process-local cache shared between requests")
    categories = _categories(records)
    rule_ids = _rule_ids(records)
    assert categories & {"architecture", "performance", "security", "reliability"}
    # must not be dominated by unrelated web-vuln standards that happen to
    # share generic words like "user"/"request"
    assert not ({"SEC-WEB-004", "SEC-WEB-005", "SEC-WEB-007"} & rule_ids), (
        f"cache/architecture query pulled in unrelated SQLi/XSS/SSRF standards: {rule_ids}"
    )


@pytest.mark.asyncio
async def test_monetary_number_precision_query_returns_relevant_domain():
    records = await _relevant_records("financial monetary amount stored using JavaScript Number")
    rule_ids = _rule_ids(records)
    assert "js_numeric_coercion_default" in rule_ids or any(
        "numeric" in (r.get("title") or "").lower() or "precision" in (r.get("title") or "").lower()
        for r in records
    ), f"expected a numeric-precision/coercion standard, got {rule_ids}"


@pytest.mark.asyncio
async def test_malformed_objectid_query_returns_relevant_domain():
    records = await _relevant_records("malformed ObjectId passed directly into Mongoose query")
    rule_ids = _rule_ids(records)
    assert "nosql_untrusted_filter" in rule_ids or "SEC-WEB-004" in rule_ids, (
        f"expected a database/query-validation standard, got {rule_ids}"
    )


@pytest.mark.asyncio
async def test_third_party_llm_privacy_query_returns_relevant_domain():
    # Phase 4: this used to be a genuine KB coverage gap (no dedicated
    # privacy/external-AI-boundary standard existed) -- AI-GEN-001 was added
    # to close it, so this now asserts the real match instead of just "not
    # obviously wrong".
    records = await _relevant_records("third-party LLM receives transaction amounts and dates")
    rule_ids = _rule_ids(records)
    categories = _categories(records)
    assert "AI-GEN-001" in rule_ids, f"expected the third-party AI data-minimization standard, got {rule_ids}"
    assert "privacy" in categories
    assert "style" not in categories


@pytest.mark.asyncio
async def test_prompt_injection_query_returns_ai_boundary_standard():
    records = await _relevant_records("untrusted OCR document text concatenated directly into an LLM prompt")
    rule_ids = _rule_ids(records)
    assert "AI-GEN-002" in rule_ids, f"expected the prompt-injection AI-boundary standard, got {rule_ids}"


@pytest.mark.asyncio
async def test_stale_cache_query_returns_cache_invalidation_standard():
    records = await _relevant_records("cached generated insight is never invalidated when the source data changes")
    rule_ids = _rule_ids(records)
    assert "CACHE-GEN-001" in rule_ids, f"expected the cache-invalidation standard, got {rule_ids}"


@pytest.mark.asyncio
async def test_duplicate_concurrent_generation_query_returns_coalescing_standard():
    records = await _relevant_records("two concurrent requests both trigger the same expensive LLM generation with no in-flight guard")
    rule_ids = _rule_ids(records)
    assert "CONC-GEN-001" in rule_ids, f"expected the request-coalescing standard, got {rule_ids}"


@pytest.mark.asyncio
async def test_user_controlled_regex_finding_query_returns_regex_standard():
    # Shaped like the real per-finding query (build_issue_knowledge_query),
    # not a bare English sentence -- that's what the pipeline actually sends.
    query = (
        "PASTE FINDING LANGUAGE: javascript\n"
        "TITLE: Search filter builds a RegExp directly from unescaped user query text\n"
        "RULE: security\nCATEGORY: security\nLINE: 12\n"
        "EVIDENCE: const filter = new RegExp(req.query.search);\n"
        "REASON: Escape regex metacharacters before constructing the pattern.\n"
        "LOCAL CODE CONTEXT:\nconst filter = new RegExp(req.query.search);\n"
    )
    records = await _relevant_records(query)
    rule_ids = _rule_ids(records)
    assert "SEC-GEN-014" in rule_ids, f"expected the user-controlled-regex standard, got {rule_ids}"


@pytest.mark.asyncio
async def test_nonsense_query_returns_nothing_or_low_confidence():
    result = await retrieve_knowledge("purple elephant dancing on the moon xyzzy", top_k=5)
    if result.get("mode") != "hybrid":
        pytest.skip("knowledge retrieval unavailable in this environment")
    # KNOWLEDGE_MIN_SCORE should discard weak semantic noise; an unrelated
    # query should return few or zero records, not a full top-k of guesses
    assert len(result["records"]) <= 2
