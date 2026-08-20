"""The 8 deterministic pattern rules, relocated unchanged from the old
services/analyzer.py. Language-gating logic (which rules run for which
language) is unchanged - only the home address changed.
"""

import re

_RE_SECRET = re.compile(r"(?i)(password|secret|api[_-]?key|token)\s*=\s*['\"][^'\"]{4,}['\"]")
_RE_EVAL_PY = re.compile(r"\b(eval|exec)\s*\(")
_RE_EVAL_JS = re.compile(r"\beval\s*\(")
_RE_BARE_EXCEPT = re.compile(r"^\s*except\s*:\s*$", re.MULTILINE)
# ponytail: spec's literal pattern (`...["'][^"'\n]*(\+|\{)`) only matches concatenation
# where + is OUTSIDE the string (e.g. "..." + var) — it can't match an f-string brace
# because that brace sits BEFORE the closing quote, not after it. Added a second
# alternative so the documented f-string case (f"SELECT ... {var}") actually fires too.
_RE_SQL_CONCAT = re.compile(
    r"(?i)(select|insert|update|delete)\b[^\"'\n]*([\"'][^\"'\n]*\+|\{[^{}\"'\n]*\}[^\"'\n]*[\"'])"
)
_RE_SUBPROCESS_SHELL = re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True")
_RE_TLS_PY = re.compile(r"verify\s*=\s*False")
_RE_TLS_NODE = re.compile(r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0")
_RE_PICKLE = re.compile(r"pickle\.loads?\(")
_RE_YAML_LOAD = re.compile(r"yaml\.load\((?!.*Loader=yaml\.SafeLoader)")
_RE_TODO = re.compile(r"(?i)#\s*(TODO|FIXME)|//\s*(TODO|FIXME)")


def _line_of(content: str, start: int) -> int:
    return content[:start].count("\n") + 1


def _evidence(match: re.Match) -> str:
    return match.group(0)[:120]


def _findings_for_pattern(content: str, path: str, pattern: re.Pattern, rule: str, severity: str, category: str, message: str) -> list[dict]:
    findings = []
    for match in pattern.finditer(content):
        findings.append(
            {
                "file": path,
                "line": _line_of(content, match.start()),
                "rule": rule,
                "severity": severity,
                "category": category,
                "message": message,
                "evidence": _evidence(match),
            }
        )
    return findings


def run_rules(path: str, language: str, content: str) -> list[dict]:
    findings = []

    # 1. hardcoded secret/credential — all languages
    findings += _findings_for_pattern(
        content, path, _RE_SECRET, "hardcoded_secret", "critical", "security",
        "Hardcoded credential-like value found",
    )

    # 2. eval/exec — language-specific pattern
    if language == "python":
        findings += _findings_for_pattern(
            content, path, _RE_EVAL_PY, "dangerous_eval", "critical", "security",
            "Use of eval/exec on potentially untrusted input",
        )
    elif language in ("javascript", "typescript"):
        findings += _findings_for_pattern(
            content, path, _RE_EVAL_JS, "dangerous_eval", "critical", "security",
            "Use of eval/exec on potentially untrusted input",
        )

    # 3. bare except — python only
    if language == "python":
        findings += _findings_for_pattern(
            content, path, _RE_BARE_EXCEPT, "bare_except", "medium", "best_practice",
            "Bare except clause silently swallows all exceptions",
        )

    # 4. SQL string concatenation — all languages
    findings += _findings_for_pattern(
        content, path, _RE_SQL_CONCAT, "sql_concat", "critical", "security",
        "Possible SQL injection via string concatenation instead of parameterized query",
    )

    # 5. subprocess shell=True — python only
    if language == "python":
        findings += _findings_for_pattern(
            content, path, _RE_SUBPROCESS_SHELL, "subprocess_shell_true", "high", "security",
            "subprocess call with shell=True risks command injection",
        )

    # 6. disabled TLS verification — python or node pattern, run both, language-gated
    if language == "python":
        findings += _findings_for_pattern(
            content, path, _RE_TLS_PY, "tls_verification_disabled", "high", "security",
            "TLS/SSL certificate verification is disabled",
        )
    if language in ("javascript", "typescript"):
        findings += _findings_for_pattern(
            content, path, _RE_TLS_NODE, "tls_verification_disabled", "high", "security",
            "TLS/SSL certificate verification is disabled",
        )

    # 7. unsafe deserialization — python only
    if language == "python":
        findings += _findings_for_pattern(
            content, path, _RE_PICKLE, "unsafe_deserialization", "high", "security",
            "Unsafe deserialization of potentially untrusted data",
        )
        findings += _findings_for_pattern(
            content, path, _RE_YAML_LOAD, "unsafe_deserialization", "high", "security",
            "Unsafe deserialization of potentially untrusted data",
        )

    # 8. TODO/FIXME markers — all languages
    findings += _findings_for_pattern(
        content, path, _RE_TODO, "todo_marker", "low", "best_practice",
        "Unresolved TODO/FIXME marker left in code",
    )

    return findings
