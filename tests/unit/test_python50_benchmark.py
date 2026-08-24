"""Real certification benchmark: 50 labeled Python fixtures with oracles.

Fixtures live in tests/fixtures/python50/ (extracted from the external
SAGE_PYTHON_50_BENCHMARK_SUITE). Each has an app.py plus an
EXPECTED_FINDINGS.json oracle -- the oracle is EVALUATION-ONLY and is
never passed to the detector as source.

CODE MASTER AI is closed-world: V1 supports exactly 11 active security families. The
benchmark's 50 fixtures deliberately span a WIDER set of themes than
that (reliability, performance, data-integrity, LLM-boundary, etc), so
this suite measures two separate things:

  IN-SCOPE RECALL  -- of the fixtures whose oracle theme maps to one of
                      the active V1 families, how many does the detector
                      catch? A miss here is a real false negative.

  OUT-OF-SCOPE     -- fixtures whose theme is outside the active V1 families
  SILENCE             MUST produce no closed-world security finding.
                      Reporting one would be a closed-world violation
                      (worse than a miss, per the GOD spec's "prefer NO
                      FINDING over MAYBE VULNERABLE" principle).
"""

import json
from pathlib import Path

import pytest

from services.analyzers.rules import run_rules
from services.security_rules import to_closed_world_findings

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "python50"

# Oracle theme -> the locked canonical family CODE MASTER AI should report for it.
# Only themes that genuinely belong to one of the active V1 families appear here;
# everything else is deliberately out of scope for the closed-world product.
THEME_TO_CANONICAL = {
    "hardcoded_secret": "SEC-HARDCODED-SECRET",
    "hardcoded_session_secret": "SEC-HARDCODED-SECRET",
    "insecure_secret_fallback": "SEC-HARDCODED-SECRET",
    "sql_injection": "SEC-SQL-INJECTION",
    "command_injection": "SEC-COMMAND-INJECTION",
    "ssrf": "SEC-SSRF",
    "path_traversal": "SEC-PATH-TRAVERSAL-FILE",
    "zip_slip": "SEC-PATH-TRAVERSAL-FILE",
    "unsafe_deserialization": "SEC-UNSAFE-DESERIALIZATION",
    "dangerous_eval": "SEC-EVAL-EXEC",
    "tls_verification_disabled": "SEC-TLS-CORS-MISCONFIG",
    "overbroad_cors": "SEC-TLS-CORS-MISCONFIG",
    "weak_password_hash": "SEC-WEAK-CRYPTO-RANDOM",
    "insecure_random_token": "SEC-WEAK-CRYPTO-RANDOM",
    "jwt_signature_disabled": "SEC-AUTH-SESSION",
}


def _load_fixtures():
    fixtures = []
    if not FIXTURE_ROOT.is_dir():
        return fixtures
    for case_dir in sorted(FIXTURE_ROOT.iterdir()):
        app = case_dir / "app.py"
        oracle_path = case_dir / "EXPECTED_FINDINGS.json"
        if not app.is_file() or not oracle_path.is_file():
            continue
        oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
        fixtures.append(
            {
                "name": case_dir.name,
                "code": app.read_text(encoding="utf-8"),
                "themes": [f["theme"] for f in oracle.get("expected_findings", [])],
            }
        )
    return fixtures


FIXTURES = _load_fixtures()
IN_SCOPE = [f for f in FIXTURES if any(t in THEME_TO_CANONICAL for t in f["themes"])]
OUT_OF_SCOPE = [f for f in FIXTURES if not any(t in THEME_TO_CANONICAL for t in f["themes"])]


def _security_findings(code: str):
    return to_closed_world_findings(run_rules("app.py", "python", code))


def test_fixture_corpus_is_present_and_substantial():
    assert len(FIXTURES) == 50, f"expected 50 benchmark fixtures, found {len(FIXTURES)}"
    assert IN_SCOPE, "expected at least some fixtures mapping to the active V1 families"


@pytest.mark.parametrize("fixture", OUT_OF_SCOPE, ids=lambda f: f["name"])
def test_out_of_scope_fixtures_produce_no_closed_world_finding(fixture):
    """Closed-world silence: a fixture whose only real issue is outside the
    active V1 families must not produce a security finding. This is the
    strictest closed-world guarantee -- reporting here would mean CODE MASTER AI
    invented a security family for a non-security (or unsupported) issue."""
    findings = _security_findings(fixture["code"])
    assert findings == [], (
        f"{fixture['name']} (themes={fixture['themes']}) is out of the active V1 scope "
        f"but produced {[f['rule_id'] for f in findings]}"
    )


def test_in_scope_recall_is_measured_and_reported(capsys):
    """Measures recall over the in-scope fixtures and asserts a floor.

    The floor is set at the currently-certified level, not at 100% -- rules
    are certified one subphase at a time (Phase 3.1..3.12), so this is a
    ratchet: it must never regress, and it rises as each subphase lands.
    """
    hits, misses = [], []
    for fixture in IN_SCOPE:
        expected = {THEME_TO_CANONICAL[t] for t in fixture["themes"] if t in THEME_TO_CANONICAL}
        got = {f["rule_id"] for f in _security_findings(fixture["code"])}
        (hits if expected & got else misses).append((fixture["name"], sorted(expected), sorted(got)))

    recall = len(hits) / len(IN_SCOPE)
    with capsys.disabled():
        print(f"\n[python50] in-scope fixtures: {len(IN_SCOPE)}  hits: {len(hits)}  recall: {recall:.0%}")
        for name, expected, got in misses:
            print(f"  MISS {name}: expected {expected}, got {got or '(nothing)'}")

    # Ratchet floor -- raise this as each Phase 3.x subphase certifies its
    # rule. Currently 65% (11/17) with Phase 3.1 (hardcoded secret) and 3.2
    # (SQL injection) certified. Known remaining misses, each owned by a
    # not-yet-run subphase:
    #   py_005 path traversal, py_006 + py_018 SSRF  -> need taint/param
    #       tracking (Phase 3.5/3.6 + Phase 4 cross-file flow)
    #   py_009 JWT signature disabled                 -> Phase 3.11
    #   py_010 + py_048 secret-via-fallback/config    -> Phase 3.11 / 3.1
    #       extension (os.getenv(...) or "literal-default" shape)
    assert recall >= 0.64, f"in-scope recall regressed to {recall:.0%}"  # 11/17 = 64.7%
