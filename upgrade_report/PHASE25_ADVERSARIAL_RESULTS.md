# Phase 2.5 Adversarial Taint QA

The adversarial suite contains 80 cases across propagation, reassignment,
branches, loops, local helpers, aliases, containers, transformations,
sanitizers, multiple sinks, safe negatives, malformed Python, file edges,
large files, repeatability, and duplicate-risk scenarios.

## Results

- Initial adversarial execution: 80 cases, 6 assertion failures after test-harness labels were corrected.
- Real implementation bugs: 4.
- Fixed bugs: 4.
- Final result: 80 passed.
- True positives: 41/41.
- True negatives: 39/39.
- False negatives: 0.
- False positives: 0.
- Precision: 1.00.
- Recall: 1.00.
- F1: 1.00.
- False-positive rate: 0.00.
- False-negative rate: 0.00.
- Crashes: 0.

Backend verification after the fixes: `347 passed, 11 skipped, 1 failed`.
The one failure was the existing live `test_benchmark_1_auth_middleware`
Groq/auth benchmark, which completed with `groq_calls=0` and no deterministic
finding; it is outside the Python taint analyzer scope.

The metrics are limited to this controlled corpus and are not a claim about
arbitrary Python programs.

## Bugs Fixed

1. Local identity helpers such as `sanitize_fake(x): return x` no longer erase taint.
2. `httpx.request("GET", url)` now tracks the URL argument rather than the method string.
3. Tainted arguments now drive sinks inside bounded local helper calls.
4. Branch and simple loop state is merged conservatively, retaining taint when any reachable path remains tainted.

## Remaining Limitations

- Analysis is Python-only, intra-file, and bounded; recursion and general interprocedural control flow are unsupported.
- Sanitizer prefixes remain a conservative naming heuristic for external functions; local identity helpers are checked, but sanitizer correctness cannot be proven without analyzing the dependency.
- Container tracking covers simple literals and fixed indexing, not arbitrary mutation, unpacking, aliasing, or data structures.
- Source recognition is intentionally limited to request/req and direct request aliases.
- Exception flow, context managers, comprehensions, generator flow, dynamic dispatch, kwargs mapping, and framework-specific wrappers are not modeled.
- Branch merging favors recall and can retain taint when path correlations would prove a value safe.

## Performance

The 5,000-line large-file case completed in under two seconds in the unit test
environment, with repeated analysis producing identical findings.
