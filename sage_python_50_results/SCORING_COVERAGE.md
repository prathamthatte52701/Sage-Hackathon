# SCORING_COVERAGE.md -- project health (7-dimension) score audit

SAGE's project-health score (`services/scoring.py`, `compute_score`) shows exactly 7 dimensions per project: security, code_quality, architecture, testing, api_design, performance, production_readiness. A dimension is `not_evaluated` (shown as no score) when there's no signal for it at all; otherwise it starts at 100 and is deducted per finding routed to it via `FINDING_CATEGORY_MAP`, plus a few structural heuristics (test-file presence, deployment-file presence, etc).

**21/50 tests (44%)** produced at least one health-score signal that would mislead a user reading only the 7-dimension summary, without inspecting individual findings. Two distinct failure shapes account for nearly all of them:

1. **Double-deduction from undeduplicated one-line-apart duplicates (7 tests)** -- a single real vulnerability gets counted twice against its dimension's score (e.g. py_004 security=70 instead of ~85, py_033 security=70, py_019 performance=84 instead of ~92). See FAILURES.md for the full duplicate list; root cause is `_dedupe_against_deterministic`'s exact-line-only matching in `services/project_review.py`.
2. **Seeded theme leaves no trace in any of the 7 dimensions (7 tests)** -- either because the theme was missed outright (py_006, py_022, py_023, py_026, py_027, py_038, py_039), or because the finding that WAS produced got routed to a dimension unrelated to what the oracle theme is actually about (py_045's pagination-input issue lands in code_quality, not api_design; py_047's debug-mode-in-production issue never touches production_readiness; py_048/py_050 only reflect one of their two seeded themes).

## Full list of flagged tests

### py_004 -- py_004_shell_injection.zip (overall_score=83.3)
- security=70 double-counts one real vulnerability as two (-15 -15) because the AI candidate duplicates the deterministic finding one line away and survived dedup -- the true single-issue severity impact is overstated.

### py_006 -- py_006_ssrf.zip (overall_score=90.6)
- security=100/evaluated is MISLEADING here: the seeded SSRF vulnerability (preview(url) fetches an arbitrary caller-supplied URL with no allow-list) was completely missed, so the security dimension shows a perfect score despite a real, high-severity seeded issue in exactly that dimension.

### py_007 -- py_007_unsafe_yaml.zip (overall_score=84.4)
- security=70 double-deducts the single real vulnerability (-15 -15) via the same missing-line-exact-match dedup gap seen in py_004.

### py_008 -- py_008_unsafe_pickle.zip (overall_score=83.3)
- security=70 double-deducts one real vulnerability, same exact-line-only dedup gap as py_004/py_007.

### py_013 -- py_013_wildcard_cors.zip (overall_score=86.8)
- security=84 double-deducts (-8 -8) one real misconfiguration via the same exact-line-only dedup gap seen elsewhere.

### py_019 -- py_019_blocking_sleep_async.zip (overall_score=88.4)
- performance=84 double-deducts (-8 -8) one real issue via the same exact-line-only dedup gap.

### py_020 -- py_020_swallowed_exception.zip (overall_score=88.7)
- code_quality=100/evaluated despite a swallowed-exception finding existing -- because the finding is tagged category=reliability (routes to architecture) rather than best_practice/correctness, the dimension a user would naturally check for 'do we have empty exception handlers' (code_quality, home of CQ-01 'never use empty or catch-all exception handling') shows a perfect, misleading 100.

### py_022 -- py_022_process_local_cache_scaling.zip (overall_score=88.8)
- architecture=92 looks like it reflects the seeded process_local_cache/scaling issue but the -8 is actually for the unrelated intra-process race-condition finding; the true seeded horizontal-scaling risk leaves no distinct trace.

### py_023 -- py_023_unbounded_memory_list.zip (overall_score=89.5)
- performance=100/evaluated is misleading: the seeded unbounded-memory-growth issue belongs squarely in the performance dimension and was never detected at all.

### py_026 -- py_026_money_float_precision.zip (overall_score=88.2)
- No dimension maps to 'financial correctness'/data-integrity for this project (data_integrity findings would route to code_quality=92, but none was produced), so the seeded float-precision risk leaves no trace anywhere in the 7-dimension score.

### py_027 -- py_027_infinity_validation.zip (overall_score=89.3)
- No dimension reflects the actual seeded data-integrity gap (infinity acceptance); code_quality=97 reflects the unrelated TypeError nit instead.

### py_033 -- py_033_zip_slip.zip (overall_score=83.3)
- security=70 double-deducts one real vulnerability (-15 -15), same exact-line-only dedup gap.

### py_036 -- py_036_predictable_token.zip (overall_score=86.4)
- security=84 double-deducts one real issue (-8 -8) via the same dedup gap.

### py_037 -- py_037_sensitive_token_logging.zip (overall_score=86.4)
- security=84 double-deducts one real issue via the same dedup gap.

### py_038 -- py_038_query_string_logging.zip (overall_score=91.1)
- security=100/evaluated and the overall 91.1 score are misleading: this is a ZERO-FINDING result on a genuinely vulnerable file (a FastAPI middleware that logs the full request URL, including query string, on every request), not a clean project.

### py_039 -- py_039_third_party_ai_privacy.zip (overall_score=86.4)
- No dimension reflects the actual seeded privacy risk (PII/financial data sent to a third party); security=85 and architecture=92 reflect two unrelated findings instead.

### py_044 -- py_044_multi_step_consistency.zip (overall_score=83.1)
- All three findings (categories logic/database/data_integrity) route to the SAME code_quality dimension (69) via FINDING_CATEGORY_MAP, so a user reading the 7-dimension breakdown would not associate 'code_quality' with a financial-transaction-atomicity problem; no dimension is labeled data-integrity/transactions specifically.

### py_045 -- py_045_unbounded_offset_pagination.zip (overall_score=88.8)
- api_design=not_evaluated even though this is precisely an API-input-boundary-validation issue (API-01 'Validate all external input at the boundary' would be the ideal citation) -- but the finding's category is best_practice, which routes to code_quality, not api_design, so both the score bucket and the citation miss the closest-matching standard.

### py_047 -- py_047_flask_debug_mode.zip (overall_score=86.8)
- production_readiness=80/evaluated: the seeded theme's own name is 'debug_mode_production' but neither finding is tagged production_readiness category, so the dimension a user would check first for this exact risk never reflects it (the -20 there is from the unrelated 'no deployment files' heuristic).

### py_048 -- py_048_csrf_cookie_form.zip (overall_score=87.8)
- security=89/evaluated does not reflect the hardcoded session secret at all -- it was never detected.

### py_050 -- py_050_tls_verification_disabled.zip (overall_score=87.8)
- security=85/evaluated reflects only the TLS finding; the second seeded high-severity theme (SSRF) leaves no trace anywhere in the score.

## Tests where the score correctly reflected the seeded issue (no flag)

29/50 tests: py_001, py_002, py_003, py_005, py_009, py_010, py_011, py_012, py_014, py_015, py_016, py_017, py_018, py_021, py_024, py_025, py_028, py_029, py_030, py_031, py_032, py_034, py_035, py_040, py_041, py_042, py_043, py_046, py_049

## api_design dimension pattern

`api_design` is `not_evaluated` in 38/50 tests (no API endpoints detected in that fixture's single function-only `app.py`) -- expected and correct behavior, not a defect, listed here for completeness: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 17, 20, 21, 23, 24, 25, 26, 27, 28, 29, 30, 31, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 49, 50]