# Phase 2 Taint Analysis Results

The deterministic Python source-to-sink corpus contains 20 true positives, 20 true negatives, and 10 adversarial cases.

- True positives: 20/20
- False negatives: 0
- False positives: 0/20 negatives
- Precision: 1.00
- Recall: 1.00
- False-positive rate: 0.00
- Stability: repeated analysis produced identical findings
- Crashes: 0, including malformed Python input

The metrics above are produced and asserted by `tests/unit/test_python_taint_corpus.py`; they cover the deliberately small Phase 2 scope, not arbitrary Python programs.
