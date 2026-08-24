"""Phase 1 acceptance suite: closed-world security rule registry + gate.

Every invariant listed in the phase-gate spec, tested directly:
  unknown rule -> rejected
  13th invented rule -> rejected
  AI-produced unsupported rule -> rejected
  RAG-produced unsupported rule -> rejected
  frontend cannot create finding (not directly testable server-side; the
    invariant this suite proves is that NOTHING -- including an
    AI-shaped dict -- can pass the gate without a mapped deterministic rule)
  finding without deterministic evidence -> rejected
  finding with fake file -> rejected
  finding with fake line -> rejected
"""

import pytest

from services.security_rules import (
    DETECTOR_RULE_TO_CANONICAL,
    SUPPORTED_SECURITY_RULES,
    is_supported_security_rule,
    to_closed_world_findings,
)


# ---------------------------------------------------------------- registry

def test_registry_has_exactly_11_active_v1_rules():
    assert len(SUPPORTED_SECURITY_RULES) == 11


def test_registry_contains_exact_locked_rule_ids():
    expected = {
        "SEC-HARDCODED-SECRET", "SEC-SQL-INJECTION", "SEC-NOSQL-INJECTION",
        "SEC-COMMAND-INJECTION", "SEC-SSRF", "SEC-PATH-TRAVERSAL-FILE",
        "SEC-UNSAFE-DESERIALIZATION", "SEC-EVAL-EXEC", "SEC-TLS-CORS-MISCONFIG",
        "SEC-WEAK-CRYPTO-RANDOM", "SEC-AUTH-SESSION",
    }
    assert set(SUPPORTED_SECURITY_RULES.keys()) == expected


def test_every_locked_rule_has_a_cwe_and_title():
    for rule_id, meta in SUPPORTED_SECURITY_RULES.items():
        assert meta.get("title"), f"{rule_id} missing title"
        assert meta.get("cwe"), f"{rule_id} missing cwe"


def test_is_supported_security_rule_accepts_locked_rules():
    for rule_id in SUPPORTED_SECURITY_RULES:
        assert is_supported_security_rule(rule_id) is True


def test_is_supported_security_rule_rejects_unknown_rule():
    assert is_supported_security_rule("SEC-XSS") is False
    assert is_supported_security_rule("") is False
    assert is_supported_security_rule(None) is False


def test_13th_invented_rule_is_rejected():
    # Simulates an agent/LLM trying to invent a new category.
    assert is_supported_security_rule("SEC-XSS-STORED") is False
    assert is_supported_security_rule("SEC-PROTOTYPE-POLLUTION") is False
    assert is_supported_security_rule("SEC-GENERIC-CODE-QUALITY") is False


# ------------------------------------------------------- detector mapping

def test_every_mapped_detector_rule_targets_a_locked_canonical_id():
    for detector_rule, canonical in DETECTOR_RULE_TO_CANONICAL.items():
        assert canonical in SUPPORTED_SECURITY_RULES, f"{detector_rule} -> {canonical} not locked"


def test_generic_non_security_detector_rules_are_not_mapped():
    # These are real detector rule ids (services/analyzers/rules.py) that
    # exist today but are NOT one of the 11 active V1 families.
    excluded = {
        "empty_exception_handler", "todo_marker", "debug_config_enabled",
        "sensitive_logging", "blocking_call_in_async", "unsafe_redirect",
        "xss_unsafe_html_sink", "react_dangerous_html", "unsafe_tempfile",
        "mongoose_money_number_no_validation", "js_numeric_coercion_default",
        "js_date_slice_without_validation", "js_zero_baseline_fallback",
        "js_unknown_type_default",
    }
    for rule in excluded:
        assert rule not in DETECTOR_RULE_TO_CANONICAL, f"{rule} should not be closed-world mapped"


# --------------------------------------------------------- positive gate

def test_supported_deterministic_finding_passes_the_gate():
    findings = [
        {"file": "config.py", "line": 3, "rule": "hardcoded_secret", "severity": "critical", "message": "x", "evidence": "API_KEY = '...'"},
    ]
    gated = to_closed_world_findings(findings)
    assert len(gated) == 1
    assert gated[0]["rule_id"] == "SEC-HARDCODED-SECRET"
    assert gated[0]["deterministic_evidence"] is True
    assert gated[0]["cwe"] == "CWE-798"


def test_python_taint_sql_injection_passes_the_locked_sql_gate():
    findings = [
        {
            "file": "app.py",
            "line": 11,
            "rule": "sql_injection",
            "severity": "critical",
            "message": "Request-derived input reaches SQL execution.",
            "evidence": 'sqlite3.connect("app.db").execute(query)',
            "evidence_type": "ast_source_sink",
        }
    ]
    gated = to_closed_world_findings(findings)
    assert len(gated) == 1
    assert gated[0]["rule_id"] == "SEC-SQL-INJECTION"
    assert gated[0]["deterministic_evidence"] is True


def test_all_active_v1_families_have_at_least_one_mapped_detector():
    mapped_canonicals = set(DETECTOR_RULE_TO_CANONICAL.values())
    assert mapped_canonicals == set(SUPPORTED_SECURITY_RULES)


def test_dependency_risk_is_not_claimed_as_active_v1_without_detector_path():
    assert "SEC-DEPENDENCY-RISK" not in SUPPORTED_SECURITY_RULES
    assert "dependency_risk" not in DETECTOR_RULE_TO_CANONICAL


def test_python_taint_command_and_ssrf_rules_pass_canonical_gate():
    findings = [
        {
            "file": "app.py",
            "line": 3,
            "rule": "command_injection",
            "severity": "critical",
            "evidence_type": "ast_source_sink",
            "evidence": "subprocess.run(cmd, shell=True)",
        },
        {
            "file": "app.py",
            "line": 8,
            "rule": "ssrf",
            "severity": "high",
            "evidence_type": "ast_source_sink",
            "evidence": "requests.get(url)",
        },
    ]

    gated = to_closed_world_findings(findings)

    assert [finding["rule_id"] for finding in gated] == ["SEC-COMMAND-INJECTION", "SEC-SSRF"]
    assert all(finding["evidence_type"] == "ast_source_sink" for finding in gated)


def test_gate_does_not_mutate_input_list():
    findings = [{"file": "a.py", "line": 1, "rule": "hardcoded_secret"}]
    original = dict(findings[0])
    to_closed_world_findings(findings)
    assert findings[0] == original


# ---------------------------------------------------------- negative gate

def test_unmapped_detector_rule_is_rejected():
    findings = [{"file": "a.py", "line": 1, "rule": "todo_marker", "severity": "low", "message": "x"}]
    assert to_closed_world_findings(findings) == []


def test_unknown_rule_string_is_rejected():
    findings = [{"file": "a.py", "line": 1, "rule": "not_a_real_rule", "severity": "low"}]
    assert to_closed_world_findings(findings) == []


def test_finding_without_deterministic_evidence_is_rejected():
    # No "rule" field at all -- can't be traced to a deterministic detector.
    findings = [{"file": "a.py", "line": 1, "message": "AI opinion with no rule"}]
    assert to_closed_world_findings(findings) == []


def test_finding_with_fake_missing_file_is_rejected():
    findings = [{"file": "", "line": 1, "rule": "hardcoded_secret"}]
    assert to_closed_world_findings(findings) == []
    findings = [{"line": 1, "rule": "hardcoded_secret"}]  # file key entirely absent
    assert to_closed_world_findings(findings) == []


def test_finding_with_fake_line_is_rejected():
    for bad_line in [0, -1, None, "not a number"]:
        findings = [{"file": "a.py", "line": bad_line, "rule": "hardcoded_secret"}]
        assert to_closed_world_findings(findings) == [], f"line={bad_line!r} should be rejected"


# -------------------------------------------------------- adversarial gate

def test_ai_produced_finding_with_invented_rule_id_is_rejected():
    # Simulates an AI quality-review finding that tries to smuggle a
    # canonical-looking rule_id directly, bypassing the detector mapping.
    ai_finding = {
        "file": "app.py",
        "line": 10,
        "rule_id": "SEC-SQL-INJECTION",  # forged canonical id, but...
        "rule": "",  # ...no real detector rule backs it
        "source": "ai_quality",
        "message": "This looks like it might have a SQL injection",
    }
    assert to_closed_world_findings([ai_finding]) == []


def test_ai_produced_finding_with_free_text_category_is_rejected():
    ai_finding = {
        "file": "app.py",
        "line": 10,
        "category": "reliability",
        "rule": "process-local cache never invalidated",  # free-text, not a detector key
        "source": "ai_quality",
    }
    assert to_closed_world_findings([ai_finding]) == []


def test_rag_produced_finding_shape_is_rejected():
    # A hypothetical RAG-originated "finding" (no detector rule at all,
    # just knowledge-base metadata masquerading as a finding).
    rag_finding = {
        "file": "app.py",
        "line": 5,
        "knowledge_id": "SEC-GEN-001",
        "rule": "SEC-GEN-001",  # KB record id, not a detector rule key
        "title": "Avoid hardcoded secrets",
    }
    assert to_closed_world_findings([rag_finding]) == []


def test_mixed_batch_keeps_only_the_valid_supported_ones():
    findings = [
        {"file": "a.py", "line": 1, "rule": "hardcoded_secret"},  # valid
        {"file": "b.py", "line": 2, "rule": "todo_marker"},  # unsupported family
        {"file": "", "line": 3, "rule": "dangerous_eval"},  # fake file
        {"file": "c.py", "line": -1, "rule": "sql_concat"},  # fake line
        {"file": "d.py", "line": 4, "rule": "ssrf_untrusted_url"},  # valid
        {"category": "architecture", "rule": "AI made this up"},  # AI-shaped junk
    ]
    gated = to_closed_world_findings(findings)
    assert {g["rule_id"] for g in gated} == {"SEC-HARDCODED-SECRET", "SEC-SSRF"}
    assert len(gated) == 2


@pytest.mark.parametrize("rule_key", list(DETECTOR_RULE_TO_CANONICAL.keys()))
def test_each_mapped_rule_individually_passes_with_valid_location(rule_key):
    findings = [{"file": "x.py", "line": 7, "rule": rule_key, "severity": "high", "message": "m", "evidence": "e"}]
    gated = to_closed_world_findings(findings)
    assert len(gated) == 1
    assert gated[0]["rule_id"] == DETECTOR_RULE_TO_CANONICAL[rule_key]


# ------------------------------------------------------ severity immutability

@pytest.mark.parametrize("severity", ["critical", "high", "medium", "low"])
def test_gate_passes_severity_through_unchanged(severity):
    # Severity is decided once, by the detector, at detection time. The gate
    # attaches rule_id/evidence_type/cwe but must never recompute or
    # override the severity a detector already assigned -- there is no
    # "central severity authority" downstream of detection, and there must
    # never be one, or severity stops being a deterministic property of the
    # vulnerability and becomes something AI/RAG could influence indirectly.
    findings = [{"file": "x.py", "line": 7, "rule": "hardcoded_secret", "severity": severity, "evidence": "API_KEY = 'x'"}]
    gated = to_closed_world_findings(findings)
    assert gated[0]["severity"] == severity


def test_gate_does_not_mutate_the_input_finding_dict():
    # Defensive proof the gate is read-only on its input, not just on the
    # severity key specifically.
    original = {"file": "x.py", "line": 7, "rule": "sql_concat", "severity": "critical", "evidence": "q"}
    snapshot = dict(original)
    to_closed_world_findings([original])
    assert original == snapshot
