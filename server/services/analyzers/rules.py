"""Deterministic pattern rules.

These checks intentionally stay evidence-first. They are not a full compiler or
framework analyzer; each rule below only fires on concrete source/config signals
with language gating and small false-positive guards where practical.
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
_RE_OS_SYSTEM = re.compile(r"\b(os\.system|os\.popen|commands\.getoutput)\s*\(")
_RE_SHELL_JS = re.compile(r"child_process\.(exec|execSync)\s*\(")
_RE_SPAWN_SHELL_JS = re.compile(r"child_process\.(spawn|spawnSync)\s*\([^)]*shell\s*:\s*true", re.DOTALL)
_RE_TLS_PY = re.compile(r"verify\s*=\s*False")
_RE_TLS_NODE = re.compile(r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0")
_RE_PICKLE = re.compile(r"pickle\.loads?\(")
_RE_YAML_LOAD = re.compile(r"yaml\.load\((?!.*Loader=yaml\.SafeLoader)")
_RE_UNSAFE_DESERIALIZE_JS = re.compile(r"node-serialize|\bunserialize\s*\(")
_RE_TODO = re.compile(r"(?i)#\s*(TODO|FIXME)|//\s*(TODO|FIXME)")
_RE_WEAK_CRYPTO_PY = re.compile(r"\b(hashlib\.(md5|sha1)\s*\(|Crypto\.Hash\.(MD5|SHA1)\b)")
_RE_WEAK_CRYPTO_JS = re.compile(r"\bcreateHash\s*\(\s*['\"](md5|sha1)['\"]\s*\)")
_RE_INSECURE_RANDOM_PY = re.compile(r"\brandom\.(random|randint|choice|choices|randrange)\s*\(")
_RE_INSECURE_RANDOM_JS = re.compile(r"\bMath\.random\s*\(")
_RE_SECURITY_TOKEN_WORD = re.compile(r"(?i)(token|secret|password|api[_-]?key|session|reset|otp|nonce)")
_RE_NOSQL_INJECTION_JS = re.compile(r"\b(find|findOne|findMany|updateOne|deleteOne)\s*\(\s*(req\.(body|query)|request\.(body|query))")
_RE_NOSQL_INJECTION_PY = re.compile(r"\b(find_one|find|update_one|delete_one)\s*\(\s*(request\.(json|args)|req\.(json|args))")
_RE_ARCHIVE_EXTRACT_PY = re.compile(r"\b(zipfile\.)?ZipFile\s*\([^)]*\)\.extractall\s*\(|\.extractall\s*\(")
_RE_ARCHIVE_EXTRACT_JS = re.compile(r"\bextractAllTo\s*\([^)]*(req\.|request\.)")
_RE_SSRF_PY = re.compile(r"\b(requests|httpx)\.(get|post|put|delete|request)\s*\(\s*(request\.(args|json)|req\.(args|json))")
_RE_SSRF_JS = re.compile(r"\b(axios|fetch|got|request)\.(get|post|put|delete|request)?\s*\(\s*(req\.(query|body)|request\.(query|body))")
_RE_XSS_JS = re.compile(r"\b(innerHTML|outerHTML)\s*=\s*[^;]*(req\.|request\.|props\.|state\.|location\.|document\.location)")
_RE_REACT_DANGEROUS_HTML = re.compile(r"dangerouslySetInnerHTML\s*=\s*\{\s*\{[^}]*(__html|html)\s*:")
_RE_CORS_WILDCARD_PY = re.compile(r"(allow_origins\s*=\s*\[\s*['\"]\*['\"]\s*\]|CORS\s*\([^)]*origins\s*=\s*['\"]\*['\"])", re.DOTALL)
_RE_CORS_WILDCARD_JS = re.compile(r"cors\s*\(\s*\{[^}]*origin\s*:\s*['\"]\*['\"]", re.DOTALL)
_RE_DEBUG_PY = re.compile(r"\b(debug\s*=\s*True|DEBUG\s*=\s*True|app\.run\s*\([^)]*debug\s*=\s*True)")
_RE_DEBUG_JS = re.compile(r"\b(DEBUG|NODE_ENV)\s*=\s*['\"]development['\"]|debug\s*:\s*true")
_RE_SENSITIVE_LOG_PY = re.compile(r"\b(log|logger)\.(debug|info|warning|error|exception)\s*\([^)]*(password|secret|token|api[_-]?key)", re.IGNORECASE)
_RE_SENSITIVE_LOG_JS = re.compile(r"\b(console|logger)\.(log|info|warn|error|debug)\s*\([^)]*(password|secret|token|api[_-]?key)", re.IGNORECASE)
_RE_ASYNC_BLOCKING_SLEEP_PY = re.compile(r"async\s+def\s+\w+\s*\([^)]*\):(?:(?!\n\s*async\s+def).)*\btime\.sleep\s*\(", re.DOTALL)
_RE_ASYNC_BLOCKING_JS = re.compile(r"async\s+(function\s+\w+|\([^)]*\)\s*=>|\w+\s*\([^)]*\)\s*\{)(?:(?!\n\s*async\s+function).)*\b(execSync|spawnSync|readFileSync|writeFileSync)\s*\(", re.DOTALL)
_RE_TEMP_MKTEMP_PY = re.compile(r"\btempfile\.mktemp\s*\(")
_RE_TEMP_TMPNAM_JS = re.compile(r"\b(tmp\.tmpNameSync|os\.tmpdir\s*\(\s*\)\s*\+)")
_RE_UNSAFE_REDIRECT_PY = re.compile(r"\bredirect\s*\(\s*(request\.(args|form|json)|req\.(args|form|json))")
_RE_UNSAFE_REDIRECT_JS = re.compile(r"\bres\.redirect\s*\(\s*(req\.(query|body|params)|request\.(query|body|params))")
_RE_LOCAL_STORAGE_TOKEN = re.compile(r"\b(localStorage|sessionStorage)\.setItem\s*\(\s*['\"][^'\"]*(token|jwt|secret|session)[^'\"]*['\"]", re.IGNORECASE)
_RE_JS_NUMERIC_COERCION_DEFAULT = re.compile(r"\bNumber\s*\([^)]*\)\s*\|\|\s*0\b")
_RE_JS_DATE_SLICE = re.compile(r"\.\s*(date|createdAt|updatedAt)\s*\.slice\s*\(")
_RE_JS_PERCENT_ZERO_BASELINE = re.compile(r"if\s*\(\s*!\s*(previous|prev|oldValue|baseline)\s*\)\s*return\s+0\s*;")
_RE_JS_UNKNOWN_TYPE_DEFAULT = re.compile(r"if\s*\([^)]*\.type\s*={2,3}\s*['\"][^'\"]+['\"][^)]*\)\s*\{[^{}]*\}\s*else\s*\{", re.DOTALL)
_RE_PLAINTEXT_PASSWORD_PY = re.compile(r"password\s*=\s*(request\.(json|form)|req\.(json|form)|input\s*\()", re.IGNORECASE)
_RE_PLAINTEXT_PASSWORD_JS = re.compile(r"(password)\s*=\s*(req\.body|request\.body)", re.IGNORECASE)
_NON_SECRET_CONTEXT = re.compile(r"(?i)(example|sample|dummy|fake|placeholder|documentation|test fixture)")
_HASH_SECURITY_CONTEXT = re.compile(r"(?i)(password|token|secret|signature|auth|credential|session)")

RULE_METADATA = {
    "hardcoded_secret": {"title": "Hardcoded credential-like value", "languages": ["any"], "category": "security"},
    "dangerous_eval": {"title": "Dynamic code execution", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "empty_exception_handler": {"title": "Empty or catch-all exception handler", "languages": ["python", "javascript", "typescript"], "category": "best_practice"},
    "sql_concat": {"title": "SQL string construction", "languages": ["any"], "category": "security"},
    "subprocess_shell_true": {"title": "Shell command execution", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "tls_verification_disabled": {"title": "TLS verification disabled", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "unsafe_deserialization": {"title": "Unsafe deserialization", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "todo_marker": {"title": "TODO/FIXME marker", "languages": ["any"], "category": "best_practice"},
    "os_system_call": {"title": "OS command execution API", "languages": ["python"], "category": "security"},
    "spawn_shell_true": {"title": "Node spawn with shell enabled", "languages": ["javascript", "typescript"], "category": "security"},
    "nosql_untrusted_filter": {"title": "Untrusted object used as NoSQL filter", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "unsafe_archive_extract": {"title": "Archive extraction without containment", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "ssrf_untrusted_url": {"title": "Outbound request to untrusted URL", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "xss_unsafe_html_sink": {"title": "Unsafe HTML rendering sink", "languages": ["javascript", "typescript"], "category": "security"},
    "react_dangerous_html": {"title": "React dangerouslySetInnerHTML", "languages": ["javascript", "typescript"], "category": "security"},
    "permissive_cors": {"title": "Permissive wildcard CORS", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "debug_config_enabled": {"title": "Debug/development config enabled", "languages": ["python", "javascript", "typescript"], "category": "best_practice"},
    "weak_crypto_hash": {"title": "Weak cryptographic hash", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "insecure_random_secret": {"title": "Insecure randomness for secret-like value", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "sensitive_logging": {"title": "Sensitive data written to logs", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "blocking_call_in_async": {"title": "Blocking call inside async handler/function", "languages": ["python", "javascript", "typescript"], "category": "performance"},
    "unsafe_tempfile": {"title": "Unsafe temporary file name generation", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "unsafe_redirect": {"title": "Redirect target controlled by request input", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "frontend_token_storage": {"title": "Auth token stored in browser storage", "languages": ["javascript", "typescript"], "category": "security"},
    "plaintext_password_handling": {"title": "Plaintext password read without hashing evidence", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "js_numeric_coercion_default": {"title": "Silent numeric coercion to zero", "languages": ["javascript", "typescript"], "category": "logic"},
    "js_date_slice_without_validation": {"title": "Date slicing without visible validation", "languages": ["javascript", "typescript"], "category": "logic"},
    "js_zero_baseline_fallback": {"title": "Zero baseline treated as missing", "languages": ["javascript", "typescript"], "category": "logic"},
    "js_unknown_type_default": {"title": "Unknown enum/type falls into default branch", "languages": ["javascript", "typescript"], "category": "logic"},
}

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


def _line_bounds(content: str, start: int, end: int) -> tuple[int, int]:
    line_start = content.rfind("\n", 0, start) + 1
    line_end = content.find("\n", end)
    if line_end == -1:
        line_end = len(content)
    return line_start, line_end


def _nearby(content: str, start: int, end: int, radius: int = 180) -> str:
    line_start, line_end = _line_bounds(content, start, end)
    return content[max(0, line_start - radius): min(len(content), line_end + radius)]


def _finding(path: str, content: str, match: re.Match, rule: str, severity: str, category: str, message: str) -> dict:
    return {
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


def _guarded_findings(content: str, path: str, pattern: re.Pattern, rule: str, severity: str, category: str, message: str, guard=None) -> list[dict]:
    findings = []
    for match in pattern.finditer(content):
        if guard and not guard(content, match):
            continue
        findings.append(_finding(path, content, match, rule, severity, category, message))
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


def _security_context_guard(content: str, match: re.Match) -> bool:
    return bool(_HASH_SECURITY_CONTEXT.search(_nearby(content, match.start(), match.end())))


def _secret_random_guard(content: str, match: re.Match) -> bool:
    return bool(_RE_SECURITY_TOKEN_WORD.search(_nearby(content, match.start(), match.end())))


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

    if language == "python":
        findings += _findings_for_pattern(
            content, path, _RE_OS_SYSTEM, "os_system_call", "high", "security",
            "Direct OS command execution API is used; ensure command input is fixed and validated",
        )
    elif language in ("javascript", "typescript"):
        findings += _findings_for_pattern(
            content, path, _RE_SPAWN_SHELL_JS, "spawn_shell_true", "high", "security",
            "child_process spawn is configured with shell=true",
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

    if language in ("javascript", "typescript"):
        findings += _findings_for_pattern(
            content, path, _RE_NOSQL_INJECTION_JS, "nosql_untrusted_filter", "high", "security",
            "Request-controlled object is passed directly as a NoSQL query filter",
        )
        findings += _findings_for_pattern(
            content, path, _RE_ARCHIVE_EXTRACT_JS, "unsafe_archive_extract", "high", "security",
            "Archive extraction target is influenced by request input",
        )
        findings += _findings_for_pattern(
            content, path, _RE_SSRF_JS, "ssrf_untrusted_url", "high", "security",
            "Outbound request URL appears to come directly from request input",
        )
        findings += _findings_for_pattern(
            content, path, _RE_XSS_JS, "xss_unsafe_html_sink", "high", "security",
            "Request, location, props, or state data is assigned to an HTML sink",
        )
        findings += _findings_for_pattern(
            content, path, _RE_REACT_DANGEROUS_HTML, "react_dangerous_html", "medium", "security",
            "React dangerouslySetInnerHTML is used and needs trusted sanitized HTML evidence",
        )
        findings += _findings_for_pattern(
            content, path, _RE_CORS_WILDCARD_JS, "permissive_cors", "medium", "security",
            "CORS is configured with a wildcard origin",
        )
        findings += _findings_for_pattern(
            content, path, _RE_DEBUG_JS, "debug_config_enabled", "medium", "best_practice",
            "Development/debug configuration appears enabled in source",
        )
        findings += _guarded_findings(
            content, path, _RE_WEAK_CRYPTO_JS, "weak_crypto_hash", "medium", "security",
            "Weak hash algorithm is used in security-adjacent code", _security_context_guard,
        )
        findings += _guarded_findings(
            content, path, _RE_INSECURE_RANDOM_JS, "insecure_random_secret", "medium", "security",
            "Math.random is used near token/secret generation", _secret_random_guard,
        )
        findings += _findings_for_pattern(
            content, path, _RE_SENSITIVE_LOG_JS, "sensitive_logging", "medium", "security",
            "Sensitive credential-like data is written to logs",
        )
        findings += _findings_for_pattern(
            content, path, _RE_ASYNC_BLOCKING_JS, "blocking_call_in_async", "medium", "performance",
            "Synchronous blocking work appears inside an async function",
        )
        findings += _findings_for_pattern(
            content, path, _RE_TEMP_TMPNAM_JS, "unsafe_tempfile", "medium", "security",
            "Temporary file path/name generation is potentially predictable or race-prone",
        )
        findings += _findings_for_pattern(
            content, path, _RE_UNSAFE_REDIRECT_JS, "unsafe_redirect", "medium", "security",
            "Redirect target appears to come directly from request input",
        )
        findings += _findings_for_pattern(
            content, path, _RE_LOCAL_STORAGE_TOKEN, "frontend_token_storage", "medium", "security",
            "Token-like value is stored in localStorage/sessionStorage",
        )
        findings += _findings_for_pattern(
            content, path, _RE_PLAINTEXT_PASSWORD_JS, "plaintext_password_handling", "high", "security",
            "Password is read from request body without visible hashing or verification context",
        )
        findings += _findings_for_pattern(
            content, path, _RE_JS_NUMERIC_COERCION_DEFAULT, "js_numeric_coercion_default", "medium", "logic",
            "Invalid numeric values are silently coerced to zero",
        )
        findings += _findings_for_pattern(
            content, path, _RE_JS_DATE_SLICE, "js_date_slice_without_validation", "low", "logic",
            "Date-like value is sliced without visible validation",
        )
        findings += _findings_for_pattern(
            content, path, _RE_JS_PERCENT_ZERO_BASELINE, "js_zero_baseline_fallback", "low", "logic",
            "Zero baseline is treated as missing by a falsy guard",
        )
        findings += _findings_for_pattern(
            content, path, _RE_JS_UNKNOWN_TYPE_DEFAULT, "js_unknown_type_default", "low", "logic",
            "Unknown type/enum values fall into a default else branch",
        )

    if language == "python":
        findings += _findings_for_pattern(
            content, path, _RE_NOSQL_INJECTION_PY, "nosql_untrusted_filter", "high", "security",
            "Request-controlled object is passed directly as a NoSQL query filter",
        )
        findings += _findings_for_pattern(
            content, path, _RE_ARCHIVE_EXTRACT_PY, "unsafe_archive_extract", "high", "security",
            "Archive extraction uses extractall without visible path containment",
        )
        findings += _findings_for_pattern(
            content, path, _RE_SSRF_PY, "ssrf_untrusted_url", "high", "security",
            "Outbound request URL appears to come directly from request input",
        )
        findings += _findings_for_pattern(
            content, path, _RE_CORS_WILDCARD_PY, "permissive_cors", "medium", "security",
            "CORS is configured with a wildcard origin",
        )
        findings += _findings_for_pattern(
            content, path, _RE_DEBUG_PY, "debug_config_enabled", "medium", "best_practice",
            "Debug configuration appears enabled in source",
        )
        findings += _guarded_findings(
            content, path, _RE_WEAK_CRYPTO_PY, "weak_crypto_hash", "medium", "security",
            "Weak hash algorithm is used in security-adjacent code", _security_context_guard,
        )
        findings += _guarded_findings(
            content, path, _RE_INSECURE_RANDOM_PY, "insecure_random_secret", "medium", "security",
            "random module is used near token/secret generation", _secret_random_guard,
        )
        findings += _findings_for_pattern(
            content, path, _RE_SENSITIVE_LOG_PY, "sensitive_logging", "medium", "security",
            "Sensitive credential-like data is written to logs",
        )
        findings += _findings_for_pattern(
            content, path, _RE_ASYNC_BLOCKING_SLEEP_PY, "blocking_call_in_async", "medium", "performance",
            "time.sleep is used inside an async function",
        )
        findings += _findings_for_pattern(
            content, path, _RE_TEMP_MKTEMP_PY, "unsafe_tempfile", "medium", "security",
            "tempfile.mktemp creates race-prone temporary paths",
        )
        findings += _findings_for_pattern(
            content, path, _RE_UNSAFE_REDIRECT_PY, "unsafe_redirect", "medium", "security",
            "Redirect target appears to come directly from request input",
        )
        findings += _findings_for_pattern(
            content, path, _RE_PLAINTEXT_PASSWORD_PY, "plaintext_password_handling", "high", "security",
            "Password is read from request input without visible hashing or verification context",
        )

    return findings
