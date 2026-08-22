# SAGE Python-50 Benchmark -- SUMMARY

Evaluation of the current SAGE application (upload -> analyze -> score -> explain-per-finding, the same path a normal SAGE user follows) against 50 labeled Python vulnerability/reliability fixtures. Oracle files (`EXPECTED_FINDINGS.json`) and the fixture `README.md` (which restates the oracle theme in prose) were never uploaded to SAGE -- only `app.py` + `requirements.txt` were sent, matching what a real user would upload as "the project."

## Per-test results

| ID | Name | Expected | Matched | Missed | FP | Duplicates | RAG (rel/irrel) | Verdict |
|----|------|----------|---------|--------|----|-----------|--------------------|---------|
| 1 | py_001_hardcoded_secret | 1 | 1 | 0 | 1 | 0 | 1/5 | PARTIAL |
| 2 | py_002_eval_untrusted_input | 1 | 1 | 0 | 0 | 0 | 1/0 | PASS |
| 3 | py_003_sql_injection | 1 | 1 | 0 | 0 | 0 | 1/1 | PARTIAL |
| 4 | py_004_shell_injection | 1 | 1 | 0 | 0 | 1 | 1/2 | PARTIAL |
| 5 | py_005_path_traversal | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 6 | py_006_ssrf | 1 | 0 | 1 | 0 | 0 | 0/2 | FAIL |
| 7 | py_007_unsafe_yaml | 1 | 1 | 0 | 0 | 1 | 1/2 | PARTIAL |
| 8 | py_008_unsafe_pickle | 1 | 1 | 0 | 0 | 1 | 1/2 | PARTIAL |
| 9 | py_009_jwt_signature_disabled | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 10 | py_010_jwt_fallback_secret | 1 | 1 | 0 | 0 | 0 | 1/3 | PARTIAL |
| 11 | py_011_missing_admin_auth | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 12 | py_012_idor_object_access | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 13 | py_013_wildcard_cors | 1 | 1 | 0 | 0 | 1 | 0/4 | PARTIAL |
| 14 | py_014_open_redirect | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 15 | py_015_raw_error_leakage | 1 | 1 | 0 | 0 | 0 | 0/4 | PARTIAL |
| 16 | py_016_unbounded_list | 1 | 1 | 0 | 0 | 0 | 0/1 | PARTIAL |
| 17 | py_017_missing_http_timeout | 1 | 1 | 0 | 0 | 0 | 0/4 | PARTIAL |
| 18 | py_018_blocking_requests_async | 2 | 2 | 0 | 0 | 0 | 0/3 | PARTIAL |
| 19 | py_019_blocking_sleep_async | 1 | 1 | 0 | 0 | 1 | 0/2 | PARTIAL |
| 20 | py_020_swallowed_exception | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 21 | py_021_global_counter_race | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 22 | py_022_process_local_cache_scaling | 1 | 0 | 1 | 0 | 0 | 0/2 | FAIL |
| 23 | py_023_unbounded_memory_list | 1 | 0 | 1 | 1 | 0 | 0/2 | FAIL |
| 24 | py_024_stale_cache_invalidation | 1 | 1 | 0 | 0 | 0 | 0/3 | PARTIAL |
| 25 | py_025_duplicate_concurrent_generation | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 26 | py_026_money_float_precision | 1 | 0 | 1 | 0 | 0 | 0/2 | FAIL |
| 27 | py_027_infinity_validation | 1 | 0 | 1 | 0 | 0 | 0/2 | FAIL |
| 28 | py_028_date_parsing_validation | 1 | 1 | 0 | 0 | 0 | 0/4 | PARTIAL |
| 29 | py_029_month_range_logic | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 30 | py_030_user_regex_redos | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 31 | py_031_predictable_temp_file | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 32 | py_032_unbounded_file_upload | 2 | 2 | 0 | 0 | 0 | 0/3 | PARTIAL |
| 33 | py_033_zip_slip | 1 | 1 | 0 | 0 | 1 | 0/4 | PARTIAL |
| 34 | py_034_world_writable_permissions | 1 | 1 | 0 | 0 | 0 | 0/4 | PARTIAL |
| 35 | py_035_weak_password_hash | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 36 | py_036_predictable_token | 1 | 1 | 0 | 0 | 1 | 0/4 | PARTIAL |
| 37 | py_037_sensitive_token_logging | 1 | 1 | 0 | 0 | 1 | 0/4 | PARTIAL |
| 38 | py_038_query_string_logging | 1 | 0 | 1 | 0 | 0 | 0/0 | FAIL |
| 39 | py_039_third_party_ai_privacy | 1 | 0 | 1 | 0 | 0 | 0/4 | FAIL |
| 40 | py_040_llm_prompt_injection_boundary | 1 | 1 | 0 | 0 | 0 | 0/4 | PARTIAL |
| 41 | py_041_llm_json_parse_failure | 1 | 1 | 0 | 0 | 0 | 0/6 | PARTIAL |
| 42 | py_042_unbounded_retry_loop | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 43 | py_043_n_plus_one_queries | 1 | 1 | 0 | 1 | 0 | 1/2 | PARTIAL |
| 44 | py_044_multi_step_consistency | 1 | 1 | 0 | 0 | 0 | 0/6 | PARTIAL |
| 45 | py_045_unbounded_offset_pagination | 1 | 1 | 0 | 0 | 0 | 0/4 | PARTIAL |
| 46 | py_046_background_task_error_loss | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 47 | py_047_flask_debug_mode | 1 | 1 | 0 | 0 | 1 | 0/4 | PARTIAL |
| 48 | py_048_csrf_cookie_form | 2 | 1 | 1 | 1 | 0 | 0/4 | PARTIAL |
| 49 | py_049_mass_assignment | 1 | 1 | 0 | 0 | 0 | 0/2 | PARTIAL |
| 50 | py_050_tls_verification_disabled | 2 | 1 | 1 | 0 | 0 | 1/0 | PARTIAL |

## Aggregate totals

- Total expected themes: **54**
- Matched: **45** | Missed: **9**
- **BENCHMARK COVERAGE = matched / expected = 45/54 = 83.3%**
- Actual unique findings across all tests: **77**
- False positive count: **4** (tests: [1, 23, 43, 48])
- Duplicate count: **9** (tests: [4, 7, 8, 13, 19, 33, 36, 37, 47])
- **BENCHMARK PRECISION (approximate) = matched / (matched + false positives) = 45/49 = 91.8%**
- RAG guidance citations: 9 relevant / 133 irrelevant
- **RAG RELEVANCE = relevant / (relevant + irrelevant) = 9/142 = 6.3%**
- Zero-finding vulnerable tests: **1** ([38])
- Hallucinated identifier/code findings: **0** -- every false positive found was grounded in real, quoted source evidence; all 4 FPs are mischaracterizations or unsubstantiated risk claims about real code, not invented files/identifiers/lines.
- Tests with a misleading score/coverage signal: **21** ([4, 6, 7, 8, 13, 19, 20, 22, 23, 26, 27, 33, 36, 37, 38, 39, 44, 45, 47, 48, 50])
- Tests with a reasoning-stage self-contradiction (finding card correct, explain-panel dismisses it): **4** ([17, 25, 39, 47])

- PASS: **1** | PARTIAL: **42** | FAIL: **7**

## Breakdown by difficulty

| Difficulty | Tests | Expected | Matched | Coverage | PASS | PARTIAL | FAIL |
|---|---|---|---|---|---|---|---|
| easy | 21 | 21 | 19 | 90.5% | 1 | 18 | 2 |
| medium | 24 | 28 | 22 | 78.6% | 0 | 20 | 4 |
| hard | 5 | 5 | 4 | 80.0% | 0 | 4 | 1 |

## Evidence-backed root-cause patterns (recur across many tests, code-cited)

1. **RAG guidance is a fixed function of category, not finding content, for the vast majority of findings.** `routers/projects.py`'s `reason_about_finding` only gets an exact, specific standard when `finding.rule` is one of the 11 ids in `RULE_TO_STANDARD` (out of ~29 deterministic rule ids, and NEVER for any `ai_quality_*`-sourced finding, since those always carry a synthetic rule name). Every other finding falls to `get_standards_for(category)[:2]` -- a static, content-blind slice of `services/standards.py`'s `STANDARDS` list. This is why the same SEC-01/SEC-02 (or CQ-01/CQ-02, or ARCH-01/ARCH-02) pairs recur verbatim across unrelated findings throughout this report -- see RAG_RELEVANCE.md.
2. **The project-analysis AI-quality pipeline runs no pre-review RAG at all.** `services/project_review.py`'s `_review_chunk` calls `build_quality_review_prompt(chunk, language, None)` -- the `knowledge` argument is hardcoded `None`, unlike the paste-review path (`routers/review.py`) which retrieves knowledge before generating candidates. `pre_rag_records` is therefore 0 for all 50 tests.
3. **One-line-apart duplicates are not deduplicated.** `_dedupe_against_deterministic` in `services/project_review.py` only drops an AI finding that shares the *exact same line number* as a deterministic one; the paste-review path's `dedupe_ai_findings` uses a +/-2 line window plus identifier/theme overlap. Project analysis has no AI-vs-AI dedup at all. Result: 9/50 tests (18%) carry a duplicate card describing one real issue twice, each contributing a double severity deduction to the health score.
4. **Reasoning-stage self-contradiction.** 4 tests (py_017, py_025, py_039, py_047) produced a correct, well-grounded finding card whose own `POST /findings/reason` ("Explain this finding") call then returned `findingConfirmed=false`, rationalizing the risk away -- 3 of 4 because the code references an `example.invalid`/`.invalid` placeholder host (a safe, deliberate RFC-2606 domain used throughout this suite), the 4th because a `if __name__=='__main__'` guard was read as "just local dev" despite that being exactly the seeded production-debug-mode bug. A counter-example (py_043) shows the same mechanism correctly rejecting a genuinely weak candidate -- so the confirm-stage isn't broken in general, but its specific "is this really production/real" heuristic is unreliable and actively undermines otherwise-correct results.
5. **Deterministic detectors miss common real-world idioms next to the classic ones they do catch.** Confirmed by direct regex testing against fixture source (not inference): `_RE_SECRET` requires the literal word secret/password/api_key/token immediately before `=`, so it misses both `app.secret_key = '...'` (py_048) and a `secret`-containing value co-located with the word "example" elsewhere in a tiny file, which trips the non-secret-context guard into suppressing a true positive (py_001). `_RE_SQL_CONCAT` cannot match the single most common Python SQL-injection idiom, `f"...WHERE x = '{var}'"` (py_003), because its brace-alternative requires `{` before any quote, and the SQL string-literal's own quote sits first. `_RE_BARE_EXCEPT` matches only a literally empty `except:`, missing the equally-common `except Exception: pass` (py_020).
6. **Inconsistent SSRF detection on an identical code shape.** The pattern `requests.get(url, timeout=N)` with `url` as a plain caller-supplied parameter (no framework route visible) is labeled SSRF correctly in py_018, but missed entirely in py_006 and py_050 -- same shape, same risk, non-deterministic outcome across 3 fixtures.
7. **STANDARDS coverage gaps.** No entry exists for SSRF, IDOR, JWT/auth, race conditions/concurrency, ReDoS, mass assignment, path traversal, CORS, open redirect, or transactional data-integrity -- so even a hypothetical exact-rule match for these themes (several of which do have deterministic detectors) would still have nowhere correct to point.

See FAILURES.md, RAG_RELEVANCE.md, and SCORING_COVERAGE.md for full detail, and per_test/py_XXX.md for every individual finding.