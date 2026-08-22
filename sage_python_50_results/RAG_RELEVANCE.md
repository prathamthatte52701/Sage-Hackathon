# RAG_RELEVANCE.md -- engineering-guidance relevance audit

Total citations attached across all findings: **142** (9 relevant / 133 irrelevant = 6.3% relevance)

## Root cause

`POST /projects/{id}/findings/reason` ("Explain this finding") is the only place a normal SAGE user sees engineering guidance for a project finding -- it is never attached automatically during `/analyze`. Its `citedStandards` field is set verbatim, server-side, from `routers/projects.py`'s `matched_standards`:

```python
standard_id = RULE_TO_STANDARD.get(finding.get("rule"))
matched_standards = [get_standard_by_id(standard_id)] if standard_id else []
if not matched_standards:
    weight_category = FINDING_CATEGORY_MAP.get(finding.get("category"))
    if weight_category:
        matched_standards = get_standards_for(weight_category, language)[:2]
```

`RULE_TO_STANDARD` covers only 11 of the ~29 deterministic rule ids, and **zero** `ai_quality_*` rule names (which is how every AI-quality-review-sourced finding is tagged) -- so the fallback branch fires for the large majority of findings across this suite. The fallback is a static, content-blind slice of `STANDARDS` by category alone: the semantic `knowledge` object computed via `retrieve_knowledge()` (visible in server logs as `[knowledge] mode=hybrid ... top=[...]`) is used only as prompt context for the LLM's prose reasoning -- it never reaches `citedStandards`.

## Citation frequency (how often each standard is cited, and how often it was actually relevant)

| Standard | Times cited | Times relevant | Relevance rate |
|---|---|---|---|
| SEC-01 | 36 | 2 | 6% |
| SEC-02 | 36 | 1 | 3% |
| CQ-01 | 15 | 0 | 0% |
| CQ-02 | 15 | 0 | 0% |
| ARCH-01 | 13 | 0 | 0% |
| ARCH-02 | 13 | 0 | 0% |
| PERF-01 | 7 | 1 | 14% |
| SEC-06 | 2 | 2 | 100% |
| SEC-03 | 1 | 1 | 100% |
| SEC-04 | 1 | 1 | 100% |
| API-01 | 1 | 0 | 0% |
| API-02 | 1 | 0 | 0% |
| SEC-05 | 1 | 1 | 100% |

SEC-01/SEC-02, CQ-01/CQ-02, and ARCH-01/ARCH-02 dominate the table by sheer volume precisely because they are each category's top-2-by-list-order -- not because they are typically relevant.

## Per-category fallback map (deterministic given the code, independent of finding content)

| Finding category | Routes to | Always cites |
|---|---|---|
| security, privacy | security | SEC-01, SEC-02 |
| best_practice, correctness, logic, database, data_integrity, maintainability | code_quality | CQ-01, CQ-02 |
| architecture, reliability | architecture | ARCH-01, ARCH-02 |
| testing | testing | TEST-01, TEST-02 |
| api_design | api_design | API-01, API-02 |
| performance | performance | PERF-01 (only entry) |
| production_readiness | production_readiness | PROD-01 (only entry) |

## Concrete misrouting examples worth reading in full (per_test files)

- **py_015**: STANDARDS actually contains `API-02: Never leak raw stack traces or exception text to API clients` -- a perfect match for its error-leakage finding. But that finding is tagged `security`, not `api_design`, so it never reaches API-02; API-02 instead lands on an unrelated missing-auth finding in the same test purely because that finding happened to be tagged `api_design`.
- **py_020**: `CQ-01: Never use empty or catch-all exception handling` is worded almost exactly for its swallowed-exception finding, but that finding is tagged `reliability` (-> architecture), so CQ-01 is unreachable.
- **py_045**: `API-01: Validate all external input at the boundary` would be the ideal citation for an unvalidated-pagination-parameter finding, unreachable because the finding is tagged `best_practice` (-> code_quality) rather than `api_design`.
- **py_043**: the sole test where the fallback citation (`PERF-01`, N+1 queries) is coincidentally and genuinely correct, because the finding itself is an actual N+1 query pattern.
- **py_010, py_050**: exact `RULE_TO_STANDARD` matches (`SEC-01` for a literal hardcoded-fallback-secret finding; `SEC-05` for `tls_verification_disabled`) -- both fully relevant, showing the mechanism works correctly whenever a rule id is actually mapped.

## STANDARDS coverage gaps evidenced by this suite

No entry exists anywhere in `services/standards.py` for: SSRF (3 tests), IDOR, JWT/authentication bypass (3 tests), missing authorization, CORS, open redirect, ReDoS, mass assignment, path traversal, race conditions/concurrency (3 tests), unsafe tempfile, insecure randomness, weak crypto hash, or transactional data-integrity. Every one of these themes appears in this 50-test suite and, when caught at all, receives only the generic category fallback.