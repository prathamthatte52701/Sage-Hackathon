Scoring status:

- Existing scoring model already represented not_evaluated dimensions and partial AI coverage.
- Implementation improved upstream coverage fields so scoring can distinguish complete vs partial semantic review more honestly.
- Critical AI severity is no longer normalized down to high in project AI review findings.

Focused scoring tests:
- tests/unit/test_scoring_dimensions.py: passed as part of focused 24-test run.
