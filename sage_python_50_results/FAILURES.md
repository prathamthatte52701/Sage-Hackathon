# FAILURES.md -- clean misses, zero-finding tests, and false positives

## FAIL-verdict tests (0 of expected themes matched)

### py_006 -- py_006_ssrf.zip
- Expected: ssrf | Missed: ssrf
- Actual findings: 1
  - app.py:3 ai_quality_reliability -- Network request errors are not caught, leading to unhandled exceptions
- Why it's a miss: Source is `def preview(url): requests.get(url, timeout=4)` -- an unvalidated caller-supplied URL fetched directly, textbook SSRF, identical in shape to py_018's requests.get(url, timeout=5) which SAGE DID correctly label SSRF. Here the AI quality review produced only one unrelated low-severity reliability nit (missing try/except) and never mentioned SSRF/untrusted destination/URL validation at all -- a genuine miss of the seeded theme, not a grounding or categorization dispute. Deterministic ssrf_untrusted_url regex also does not fire (it only matches requests.get(request.args/json...) as the literal first argument, not a plain function parameter named url), so nothing else backstops the miss. This is direct evidence of inconsistent AI detection on near-identical vulnerable code shapes across fixtures. Negative assertion (timeout=4 present) correctly not violated.

### py_022 -- py_022_process_local_cache_scaling.zip
- Expected: process_local_cache | Missed: process_local_cache
- Actual findings: 1
  - app.py:4 ai_quality_reliability -- Shared mutable cache (profile_cache) accessed without concurrency protection may cause race conditions in async environment
- Why it's a miss: Judgment call: oracle theme process_local_cache is about the cache existing ONLY in process memory, so it silently diverges/loses data across multiple server instances/workers (a horizontal-scaling / architecture concern -- oracle evidence: 'Mutable cache exists only in process memory'). The actual finding instead describes a same-process async race condition (concurrent requests racing on one dict within a single process) -- a related but genuinely different risk, with no mention anywhere of multiple processes, workers, instances, or horizontal scaling. Per the semantic-matching rule (same underlying risk required, not just shared subject/variable), this does not count as a match. Treated as a clean miss (0/1) since the finding, while accurate on its own terms, does not address the seeded risk at all.

### py_023 -- py_023_unbounded_memory_list.zip
- Expected: unbounded_memory_growth | Missed: unbounded_memory_growth
- Actual findings: 1
  - app.py:2 ai_quality_reliability -- Global mutable list 'recent_events' is accessed without any concurrency control, leading to potential race conditions in multi-threaded contexts. [FALSE POSITIVE]
- Why it's a miss: Clean miss on a 4-line fixture with an obvious, single seeded issue: recent_events grows forever with no cap/eviction. Instead the model speculated about multi-threaded race conditions with no supporting evidence, and its own explain-stage correctly rejected that speculative claim (findingConfirmed=false) -- so the net useful signal on this test is zero.

### py_026 -- py_026_money_float_precision.zip
- Expected: financial_float_precision | Missed: financial_float_precision
- Actual findings: 1
  - app.py:2 ai_quality_correctness -- Potential division by zero when 'people' is zero or negative
- Why it's a miss: Source: checkout_total sums a list[float] of prices and computes tax as float arithmetic, split_bill divides a float total -- money represented entirely in binary float, the seeded issue (oracle evidence: 'Money calculations use binary floating point'). The single AI finding produced instead flags an unrelated (if legitimate) division-by-zero edge case in split_bill and never mentions floating-point/Decimal/rounding at all. Full 2-line file was sent to the model in one chunk, so this is a genuine reasoning miss, not a truncation/coverage artifact. Zero useful findings on the actual seeded theme.

### py_027 -- py_027_infinity_validation.zip
- Expected: finite_number_validation | Missed: finite_number_validation
- Actual findings: 1
  - app.py:2 ai_quality_correctness -- Non-numeric inputs cause unhandled TypeError when converting to float
- Why it's a miss: Source explicitly checks math.isnan(amount) and amount<0 but never math.isinf(amount) -- float('inf') sails through as a 'valid' normalized amount, exactly the oracle's seeded gap ('NaN is rejected but positive infinity is accepted'), sitting directly adjacent to the two checks that DO exist. The AI instead raised an unrelated, real-but-different concern (TypeError on non-numeric strings) and never mentioned infinity, isinf, or unbounded magnitude at all. Notable miss given how localized and structurally obvious the gap is (three consecutive if/raise lines, missing exactly one).

### py_038 -- py_038_query_string_logging.zip
- Expected: sensitive_url_logging | Missed: sensitive_url_logging
- Actual findings: 0
- Why it's a miss: ZERO-FINDING VULNERABLE TEST. Source: `logger.info('request_url=%s', str(request.url))` inside a global HTTP middleware -- every request's full URL, including any query-string secrets/tokens/PII, is logged unconditionally. The Groq quality-review call for this file returned zero issues (ai_candidate_count=0, not merely grounding-rejected candidates) -- a complete miss with no compensating deterministic rule (sensitive_logging's regex only matches password/secret/token/api_key keywords near a log call, not a URL-object being logged). This is the clearest complete-miss case in the batch: one 7-line file, one obvious, single seeded issue, zero output.

### py_039 -- py_039_third_party_ai_privacy.zip
- Expected: third_party_ai_privacy | Missed: third_party_ai_privacy
- Actual findings: 2
  - app.py:3 ai_quality_security -- The external AI endpoint is called without authentication, allowing unauthenticated use and potential abuse.
  - app.py:3 ai_quality_reliability -- Network errors or non-200 responses are not handled
- Why it's a miss: Source builds payload={'name','email','transactions','account_number'} and POSTs it wholesale to an external AI endpoint -- an obvious, named-field PII/financial data-minimization risk (the exact theme, 'third_party_ai_privacy'). Neither finding mentions the payload contents, data sent, privacy, PII, or data minimization at all; both are about unrelated concerns (missing outbound auth, missing error handling). Negative assertion correctly respected (timeout=10 present, not flagged). Also the 4th occurrence of the example.invalid-triggered reasoning self-contradiction.

## Zero-finding vulnerable tests

- py_038 (py_038_query_string_logging.zip): 0 findings produced; expected sensitive_url_logging. ZERO-FINDING VULNERABLE TEST. Source: `logger.info('request_url=%s', str(request.url))` inside a global HTTP middleware -- every request's full URL, including any query-string secrets/tokens/PII, is logged unconditionally. The Groq quality-review call for this file returned zero issues (ai_candidate_count=0, not merely grounding-rejected candidates) -- a complete miss with no compensating deterministic rule (sensitive_logging's regex only matches password/secret/token/api_key keywords near a log call, not a URL-object being logged). This is the clearest complete-miss case in the batch: one 7-line file, one obvious, single seeded issue, zero output.

## All false positives (across every verdict, not just FAIL)

### py_001 -- py_001_hardcoded_secret.zip, finding[1] app.py:3
- Claim: User-provided identifier is interpolated into a URL without validation, risking path-traversal or SSRF
- Evidence quoted: `requests.get(f"https://example.invalid/users/{user_id}", ...)`
- Why unsupported: Host is a fixed literal (example.invalid); user_id only affects a URL path segment. Neither SSRF (no attacker-controlled destination host) nor path-traversal (no filesystem path involved) actually applies to this code shape; a milder 'unvalidated input in URL path' framing would have been accurate but SSRF/path-traversal is unsupported.

### py_023 -- py_023_unbounded_memory_list.zip, finding[0] app.py:2
- Claim: Global mutable list 'recent_events' is accessed without any concurrency control, leading to potential race conditions in multi-threaded contexts.
- Evidence quoted: `recent_events=[]
def record_event(name: str): recent_events.append({'name':name,'ts':time.time()})
def recent_count(): return len(recent_events)`
- Why unsupported: Speculative concurrency claim with zero evidence of threading/async/server context in this 4-line pure-function file (no imports beyond time, no framework). The finding's own downstream reasoning stage independently agrees: findingConfirmed=false, 'no evidence ... of multi-threaded execution.' Misses the actual, much more obvious seeded issue entirely: recent_events.append() runs unboundedly with no cap/eviction.

### py_043 -- py_043_n_plus_one_queries.zip, finding[1] app.py:3
- Claim: Potential None author not handled, may cause downstream errors
- Evidence quoted: `author=db.execute('SELECT id,name FROM users WHERE id = ?', (post['author_id'],)).fetchone()`
- Why unsupported: The finding's own explain-stage (findingConfirmed=false) correctly notes the code shown never dereferences 'author' in a way that would break if it were None -- speculative, unsubstantiated by the visible code. This is a case where the self-check worked as intended (contrast with py_017/023/025/039 where the same mechanism dismissed a genuinely correct finding).

### py_048 -- py_048_csrf_cookie_form.zip, finding[0] app.py:6
- Claim: User-provided email is accepted without any validation
- Evidence quoted: `new_email=request.form['email']`
- Why unsupported: Own explain-stage (findingConfirmed=false) correctly notes the shown code only echoes new_email back without storing it, querying with it, or otherwise using it dangerously -- unsubstantiated by the visible code, same legitimate self-correction pattern as py_043.

## Reasoning-stage self-contradictions (finding card correct, explain-panel dismisses it)

### py_017 -- py_017_missing_http_timeout.zip, finding[0] app.py:3
- Card: Outbound HTTP request lacks a timeout, risking indefinite hangs.
- Contradiction: confirm_and_explain_finding returned findingConfirmed=false, reasoning that 'example.invalid' is a placeholder/documentation domain so 'the code is not making a real outbound request in production' -- but this fixture's seeded issue IS that the timeout is genuinely missing (no negative assertion here, unlike py_001/006/018/039/050 where timeout IS present and correctly not flagged). The finding card itself is accurate; the explain-stage second-guesses a correct finding for an irrelevant reason.

### py_017 -- py_017_missing_http_timeout.zip, finding[1] app.py:3
- Card: User-provided 'base' and 'quote' values are interpolated directly into the URL without validation
- Contradiction: same findingConfirmed=false / example.invalid rationalization as finding 0

### py_025 -- py_025_duplicate_concurrent_generation.zip, finding[0] app.py:4
- Card: Potential race condition when multiple coroutines access and modify the shared 'results' dict without synchronization
- Contradiction: confirm_and_explain_finding returned findingConfirmed=false, reasoning 'the subsequent writes store the same value, so data integrity isn't affected' -- this misreads the seeded risk: request_coalescing_missing is about wastefully calling the (implicitly expensive) provider.generate(key) TWICE concurrently for the same key, not about the final stored value being correct. The card itself is precisely and correctly grounded on the exact race window named by the oracle; the explain-stage talks the user out of a hard-difficulty, correctly-caught finding.

### py_039 -- py_039_third_party_ai_privacy.zip, finding[0] app.py:3
- Card: The external AI endpoint is called without authentication, allowing unauthenticated use and potential abuse.
- Contradiction: findingConfirmed=false, reasoning '.invalid TLD ... indicating this is not a production external AI service' -- same example.invalid dismissal pattern as py_017/023/025 (4th occurrence).

### py_047 -- py_047_flask_debug_mode.zip, finding[1] app.py:5
- Card: Debug mode is enabled in the Flask app when running as __main__
- Contradiction: findingConfirmed=false, reasoning 'typical for local development and testing ... no evidence ... runs in production' -- but this fixture's entire seeded point IS that debug=True under if __name__=='__main__' ships to production (oracle theme literally named debug_mode_production). 5th self-contradiction instance in this batch, and the first NOT triggered by an example.invalid domain -- shows the dismissal pattern generalizes to any code shape the model associates with 'just local dev'.

## Duplicate-finding tests (one root cause, two user-visible cards)

- py_004 (py_004_shell_injection.zip): finding[1] duplicates 0 -- both describe the same root cause one line apart, not deduplicated by `_dedupe_against_deterministic`.
- py_007 (py_007_unsafe_yaml.zip): finding[1] duplicates 0 -- both describe the same root cause one line apart, not deduplicated by `_dedupe_against_deterministic`.
- py_008 (py_008_unsafe_pickle.zip): finding[1] duplicates 0 -- both describe the same root cause one line apart, not deduplicated by `_dedupe_against_deterministic`.
- py_013 (py_013_wildcard_cors.zip): finding[1] duplicates 0 -- both describe the same root cause one line apart, not deduplicated by `_dedupe_against_deterministic`.
- py_019 (py_019_blocking_sleep_async.zip): finding[1] duplicates 0 -- both describe the same root cause one line apart, not deduplicated by `_dedupe_against_deterministic`.
- py_033 (py_033_zip_slip.zip): finding[1] duplicates 0 -- both describe the same root cause one line apart, not deduplicated by `_dedupe_against_deterministic`.
- py_036 (py_036_predictable_token.zip): finding[1] duplicates 0 -- both describe the same root cause one line apart, not deduplicated by `_dedupe_against_deterministic`.
- py_037 (py_037_sensitive_token_logging.zip): finding[1] duplicates 0 -- both describe the same root cause one line apart, not deduplicated by `_dedupe_against_deterministic`.
- py_047 (py_047_flask_debug_mode.zip): finding[1] duplicates 0 -- both describe the same root cause one line apart, not deduplicated by `_dedupe_against_deterministic`.
