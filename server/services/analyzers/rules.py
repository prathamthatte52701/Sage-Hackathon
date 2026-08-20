"""The 8 deterministic pattern rules. Python and JavaScript/TypeScript now
have equal coverage on all 8; Java/C++ still only get the 3 language-neutral
checks (secrets, SQL concat, TODO markers) - that's an accepted, explicit
limitation, not something this pass fixes.
"""

import re

_RE_SECRET = re.compile(r"(?i)(password|secret|api[_-]?key|token)\s*=\s*['\"][^'\"]{4,}['\"]")
_RE_EVAL_PY = re.compile(r"\b(eval|exec)\s*\(")
_RE_EVAL_JS = re.compile(r"\beval\s*\(")
_RE_BARE_EXCEPT = re.compile(r"^\s*except\s*:\s*$", re.MULTILINE)
_RE_EMPTY_CATCH_JS = re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}")
# ponytail: spec's literal pattern (`...["'][^"'\n]*(\+|\{)`) only matches concatenation
# where + is OUTSIDE the string (e.g. "..." + var) — it can't match an f-string brace
# because that brace sits BEFORE the closing quote, not after it. Added a second
# alternative so the documented f-string case (f"SELECT ... {var}") actually fires too.
_RE_SQL_CONCAT = re.compile(
    r"(?i)(select|insert|update|delete)\b[^\"'\n]*([\"'][^\"'\n]*\+|\{[^{}\"'\n]*\}[^\"'\n]*[\"'])"
)
_RE_SUBPROCESS_SHELL = re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True")
_RE_SHELL_JS = re.compile(r"child_process\.(exec|execSync)\s*\(")
_RE_TLS_PY = re.compile(r"verify\s*=\s*False")
_RE_TLS_NODE = re.compile(r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0")
_RE_PICKLE = re.compile(r"pickle\.loads?\(")
_RE_YAML_LOAD = re.compile(r"yaml\.load\((?!.*Loader=yaml\.SafeLoader)")
_RE_UNSAFE_DESERIALIZE_JS = re.compile(r"node-serialize|\bunserialize\s*\(")
_RE_TODO = re.compile(r"(?i)#\s*(TODO|FIXME)|//\s*(TODO|FIXME)")
_NON_SECRET_CONTEXT = re.compile(r"(?i)(example|sample|dummy|fake|placeholder|documentation|test fixture)")

# language-gated pattern tables for the 3 checks that only covered Python
# before this — Java/C++ intentionally absent, out of scope.
EMPTY_CATCH_PATTERNS = {
    "python": _RE_BARE_EXCEPT,
    "javascript": _RE_EMPTY_CATCH_JS,
    "typescript": _RE_EMPTY_CATCH_JS,
}
SHELL_INJECTION_PATTERNS = {
    "python": _RE_SUBPROCESS_SHELL,
    "javascript": _RE_SHELL_JS,
    "typescript": _RE_SHELL_JS,
}
DESERIALIZATION_PATTERNS = {
    "python": [_RE_PICKLE, _RE_YAML_LOAD],
    "javascript": [_RE_UNSAFE_DESERIALIZE_JS],
    "typescript": [_RE_UNSAFE_DESERIALIZE_JS],
}


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
                "confidence": "medium",
                "evidence_type": "deterministic_pattern",
            }
        )
    return findings


def _is_comment_or_non_secret_context(content: str, match: re.Match) -> bool:
    line_start = content.rfind("\n", 0, match.start()) + 1
    line_end = content.find("\n", match.end())
    if line_end == -1:
        line_end = len(content)
    line = content[line_start:line_end]
    stripped = line.strip()
    if stripped.startswith(("#", "//", "/*", "*")):
        return True
    nearby = content[max(0, line_start - 180): min(len(content), line_end + 180)]
    return bool(_NON_SECRET_CONTEXT.search(nearby))


def run_rules(path: str, language: str, content: str) -> list[dict]:
    findings = []

    # 1. hardcoded secret/credential — all languages
    for match in _RE_SECRET.finditer(content):
        if _is_comment_or_non_secret_context(content, match):
            continue
        findings.append(
            {
                "file": path,
                "line": _line_of(content, match.start()),
                "rule": "hardcoded_secret",
                "severity": "critical",
                "category": "security",
                "message": "Hardcoded credential-like value found",
                "evidence": _evidence(match),
                "confidence": "medium",
                "evidence_type": "deterministic_pattern",
            }
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

    # 3. empty / catch-all exception handling — python + js/ts
    pattern = EMPTY_CATCH_PATTERNS.get(language)
    if pattern:
        findings += _findings_for_pattern(
            content, path, pattern, "empty_exception_handler", "medium", "best_practice",
            "Empty or catch-all exception handler silently swallows all errors",
        )

    # 4. SQL string concatenation — all languages
    findings += _findings_for_pattern(
        content, path, _RE_SQL_CONCAT, "sql_concat", "critical", "security",
        "Possible SQL injection via string concatenation instead of parameterized query",
    )

    # 5. shell / command injection risk — python + js/ts
    pattern = SHELL_INJECTION_PATTERNS.get(language)
    if pattern:
        findings += _findings_for_pattern(
            content, path, pattern, "subprocess_shell_true", "high", "security",
            "Shell/subprocess call with an unsanitized command string risks command injection",
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

    # 7. unsafe deserialization — python + js/ts
    for pattern in DESERIALIZATION_PATTERNS.get(language, []):
        findings += _findings_for_pattern(
            content, path, pattern, "unsafe_deserialization", "high", "security",
            "Unsafe deserialization of potentially untrusted data",
        )

    # 8. TODO/FIXME markers — all languages
    findings += _findings_for_pattern(
        content, path, _RE_TODO, "todo_marker", "low", "best_practice",
        "Unresolved TODO/FIXME marker left in code",
    )

    return findings
