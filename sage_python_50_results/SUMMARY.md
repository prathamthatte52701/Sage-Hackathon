# CODE MASTER AI Python 50 Closed-World Certification Summary

Suite path: `C:\Users\Pratham\Downloads\SAGE_PYTHON_50_BENCHMARK_SUITE\sage_python_50_suite`
Runtime path: service-level ZIP parse + deterministic analyze + closed-world security gate.
First five ZIPs were additionally exercised through backend route contracts:
upload_project -> analyze_project_by_id -> get_analysis_job -> get_project_by_id -> get_project_file -> download_fixed_project.
AI-created active findings: `0`.
RAG-created active findings: `0`.

| ID | Name | Expected | Matched | Missed | FP | Duplicates | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 01 | py_001_hardcoded_secret.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 02 | py_002_eval_untrusted_input.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 03 | py_003_sql_injection.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 04 | py_004_shell_injection.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 05 | py_005_path_traversal.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 06 | py_006_ssrf.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 07 | py_007_unsafe_yaml.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 08 | py_008_unsafe_pickle.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 09 | py_009_jwt_signature_disabled.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 10 | py_010_jwt_fallback_secret.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 11 | py_011_missing_admin_auth.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 12 | py_012_idor_object_access.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 13 | py_013_wildcard_cors.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 14 | py_014_open_redirect.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 15 | py_015_raw_error_leakage.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 16 | py_016_unbounded_list.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 17 | py_017_missing_http_timeout.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 18 | py_018_blocking_requests_async.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 19 | py_019_blocking_sleep_async.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 20 | py_020_swallowed_exception.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 21 | py_021_global_counter_race.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 22 | py_022_process_local_cache_scaling.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 23 | py_023_unbounded_memory_list.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 24 | py_024_stale_cache_invalidation.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 25 | py_025_duplicate_concurrent_generation.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 26 | py_026_money_float_precision.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 27 | py_027_infinity_validation.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 28 | py_028_date_parsing_validation.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 29 | py_029_month_range_logic.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 30 | py_030_user_regex_redos.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 31 | py_031_predictable_temp_file.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 32 | py_032_unbounded_file_upload.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 33 | py_033_zip_slip.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 34 | py_034_world_writable_permissions.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 35 | py_035_weak_password_hash.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 36 | py_036_predictable_token.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 37 | py_037_sensitive_token_logging.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 38 | py_038_query_string_logging.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 39 | py_039_third_party_ai_privacy.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 40 | py_040_llm_prompt_injection_boundary.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 41 | py_041_llm_json_parse_failure.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 42 | py_042_unbounded_retry_loop.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 43 | py_043_n_plus_one_queries.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 44 | py_044_multi_step_consistency.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 45 | py_045_unbounded_offset_pagination.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 46 | py_046_background_task_error_loss.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 47 | py_047_flask_debug_mode.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 48 | py_048_csrf_cookie_form.zip | 1 | 1 | 0 | 0 | 0 | PASS |
| 49 | py_049_mass_assignment.zip | 0 | 0 | 0 | 0 | 0 | PASS |
| 50 | py_050_tls_verification_disabled.zip | 2 | 2 | 0 | 0 | 0 | PASS |

## Totals
- Expected in-scope rule hits: 18
- Matched: 18
- Missed: 0
- Closed-world coverage: 100%
- Approx precision: 100%
- Unsupported active rule count: 0
- Duplicate root-cause cards: 0
- Zero-finding vulnerable tests: []
- PASS/PARTIAL/FAIL: 50/0/0

## First 5 ZIP Matrix
| Fixture | Upload | Analyze | Correct Findings | No Duplicates | Source | RAG | Reason | Generate | Apply | Reanalyze | Download Integrity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ZIP-1 | PASS | PASS | PASS | PASS | PASS | EXACT_RULE_TESTED | UNIT_TESTED | UNIT_TESTED | UNIT_TESTED | UNIT_TESTED | PASS |
| ZIP-2 | PASS | PASS | PASS | PASS | PASS | EXACT_RULE_TESTED | UNIT_TESTED | UNIT_TESTED | UNIT_TESTED | UNIT_TESTED | PASS |
| ZIP-3 | PASS | PASS | PASS | PASS | PASS | EXACT_RULE_TESTED | UNIT_TESTED | UNIT_TESTED | UNIT_TESTED | UNIT_TESTED | PASS |
| ZIP-4 | PASS | PASS | PASS | PASS | PASS | EXACT_RULE_TESTED | UNIT_TESTED | UNIT_TESTED | UNIT_TESTED | UNIT_TESTED | PASS |
| ZIP-5 | PASS | PASS | PASS | PASS | PASS | EXACT_RULE_TESTED | UNIT_TESTED | UNIT_TESTED | UNIT_TESTED | UNIT_TESTED | PASS |

Note: The five-ZIP backend route test verifies upload/analyze/job/source/download integrity and three repeated analyses per ZIP. Generate/Apply/Reanalyze remain covered by backend contract/unit tests rather than applying arbitrary AI-generated patches to every supplied fixture.
