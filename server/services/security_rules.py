"""Phase 1: closed-world security rule registry.

SAGE is a closed-world security reviewer supporting EXACTLY these 12 locked
rule families. This is permanent product scope -- no coding agent, LLM, RAG
document, or frontend component may introduce a 13th category.

No finding -- from any source (deterministic detector, AI explanation
engine, RAG) -- may reach the active closed-world product output unless its
rule_id is a member of SUPPORTED_SECURITY_RULES and it carries
deterministic_evidence=True. AI does not create findings; this module is
what makes that a structural gate rather than a prompting discipline.
"""

SUPPORTED_SECURITY_RULES = {
    "SEC-HARDCODED-SECRET": {"title": "Hardcoded credential-like value", "cwe": "CWE-798"},
    "SEC-SQL-INJECTION": {"title": "SQL injection", "cwe": "CWE-89"},
    "SEC-NOSQL-INJECTION": {"title": "NoSQL injection", "cwe": "CWE-943"},
    "SEC-COMMAND-INJECTION": {"title": "OS command injection", "cwe": "CWE-78"},
    "SEC-SSRF": {"title": "Server-side request forgery", "cwe": "CWE-918"},
    "SEC-PATH-TRAVERSAL-FILE": {"title": "Path traversal / unsafe file handling", "cwe": "CWE-22"},
    "SEC-UNSAFE-DESERIALIZATION": {"title": "Unsafe deserialization", "cwe": "CWE-502"},
    "SEC-EVAL-EXEC": {"title": "Dynamic code execution (eval/exec)", "cwe": "CWE-95"},
    "SEC-TLS-CORS-MISCONFIG": {"title": "TLS/CORS misconfiguration", "cwe": "CWE-295"},
    "SEC-WEAK-CRYPTO-RANDOM": {"title": "Weak cryptography / insecure randomness", "cwe": "CWE-330"},
    "SEC-AUTH-SESSION": {"title": "Authentication/session security", "cwe": "CWE-287"},
    "SEC-DEPENDENCY-RISK": {"title": "Dependency risk", "cwe": "CWE-1104"},
}

# Findings whose evidence is a single concrete pattern match (a literal
# secret, a dangerous call) rather than a traced source->sink path. Taint-
# capable rules get "taint_flow" once Phase 4 wires actual path evidence;
# until then they're reported as "ast_call" since that's genuinely what the
# current detector evidence is -- a matched call/pattern, not a traced flow.
_LITERAL_EVIDENCE_RULES = {"SEC-HARDCODED-SECRET"}


def is_supported_security_rule(rule_id) -> bool:
    return rule_id in SUPPORTED_SECURITY_RULES


# Maps existing deterministic detector rule strings (services/analyzers/rules.py
# RULE_METADATA keys) onto the locked canonical registry. A detector rule with
# no entry here does not belong to one of the 12 families (or isn't deep/
# certified enough yet) and must not reach the closed-world output.
#
# Deliberately NOT mapped -- existing detectors, but outside the locked 12,
# or not yet certified: empty_exception_handler, todo_marker,
# debug_config_enabled, sensitive_logging, blocking_call_in_async,
# unsafe_redirect, xss_unsafe_html_sink, react_dangerous_html,
# unsafe_tempfile, mongoose_money_number_no_validation,
# js_numeric_coercion_default, js_date_slice_without_validation,
# js_zero_baseline_fallback, js_unknown_type_default.
DETECTOR_RULE_TO_CANONICAL = {
    "hardcoded_secret": "SEC-HARDCODED-SECRET",
    "sql_concat": "SEC-SQL-INJECTION",
    "nosql_untrusted_filter": "SEC-NOSQL-INJECTION",
    "subprocess_shell_true": "SEC-COMMAND-INJECTION",
    "os_system_call": "SEC-COMMAND-INJECTION",
    "spawn_shell_true": "SEC-COMMAND-INJECTION",
    "ssrf_untrusted_url": "SEC-SSRF",
    "path_traversal_file": "SEC-PATH-TRAVERSAL-FILE",
    "unsafe_archive_extract": "SEC-PATH-TRAVERSAL-FILE",
    "unsafe_deserialization": "SEC-UNSAFE-DESERIALIZATION",
    "dangerous_eval": "SEC-EVAL-EXEC",
    "tls_verification_disabled": "SEC-TLS-CORS-MISCONFIG",
    "permissive_cors": "SEC-TLS-CORS-MISCONFIG",
    "weak_crypto_hash": "SEC-WEAK-CRYPTO-RANDOM",
    "insecure_random_secret": "SEC-WEAK-CRYPTO-RANDOM",
    "frontend_token_storage": "SEC-AUTH-SESSION",
    "plaintext_password_handling": "SEC-AUTH-SESSION",
    "process_global_auth_cache": "SEC-AUTH-SESSION",
}


def _has_real_location(finding: dict) -> bool:
    """A finding must name a real file and a real (positive) line to be
    trustworthy -- an empty/missing file or a non-positive line number is
    fabricated-evidence-shaped, not a location a human can go verify."""
    file = finding.get("file")
    line = finding.get("line")
    if not file or not isinstance(file, str):
        return False
    if not isinstance(line, int) or isinstance(line, bool) or line <= 0:
        return False
    return True


def to_closed_world_findings(findings: list) -> list[dict]:
    """THE gate. Every finding -- deterministic or AI-produced -- must pass
    through this before it can appear in closed-world product output.

    Applies uniformly regardless of source: a deterministic detector finding
    passes only if (a) its rule maps to one of the 12 canonical families and
    (b) it has a real file/line. An AI-quality-review finding has no rule
    string that maps here (AI findings use free-text categories like
    "reliability", never one of the mapped detector strings), so it is
    unconditionally dropped -- this is what makes "AI does not create
    findings" a structural property instead of a prompting convention.

    Accepts finding dicts OR objects with matching attributes (e.g. Issue).
    Returns new plain dicts; never mutates input.
    """
    kept = []
    for finding in findings:
        get = finding.get if isinstance(finding, dict) else lambda k, d=None: getattr(finding, k, d)
        rule_key = get("rule")
        canonical = DETECTOR_RULE_TO_CANONICAL.get(rule_key)
        if canonical is None:
            continue
        as_dict = dict(finding) if isinstance(finding, dict) else finding.model_dump() if hasattr(finding, "model_dump") else vars(finding)
        if not _has_real_location(as_dict):
            continue
        gated = dict(as_dict)
        gated["rule_id"] = canonical
        gated["deterministic_evidence"] = True
        gated["evidence_type"] = "literal_secret" if canonical in _LITERAL_EVIDENCE_RULES else "ast_call"
        gated["cwe"] = SUPPORTED_SECURITY_RULES[canonical]["cwe"]
        kept.append(gated)
    return kept
