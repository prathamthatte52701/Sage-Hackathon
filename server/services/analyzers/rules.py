"""Deterministic pattern rules.

These checks intentionally stay evidence-first. They are not a full compiler or
framework analyzer; each rule below only fires on concrete source/config signals
with language gating and small false-positive guards where practical.
"""

import ast
import io
import re
import tokenize

_RE_SECRET = re.compile(r"(?i)(password|secret(?:[_-]?key)?|api[_-]?key|token)\s*=\s*['\"]([^'\"]{4,})['\"]")

# GOD spec Rule 1: "DO NOT report password = 'hello' / token = 'test' /
# secret = 'example' automatically" -- a credential-shaped assignment whose
# VALUE is itself a common weak/placeholder word is evidence of a test
# fixture or a lazy default, not a real embedded credential. Checked
# case-insensitively against the whole value and against alphabetic-only
# runs within it (so "changeme123", "testpassword", "xxxxadminxxxx" are
# still caught, but a real high-entropy secret containing "test" as a
# substring, e.g. an actual key from a provider's test-mode key space
# with real random suffix, is judged on the whole value, not blocklisted
# for merely containing "test").
_WEAK_SECRET_VALUES = {
    "hello", "test", "example", "changeme", "password", "admin", "adminadmin",
    "12345", "123456", "1234567", "12345678", "123456789", "qwerty", "letmein",
    "welcome", "secret", "default", "changeit", "placeholder", "xxx", "xxxx",
    "yourpassword", "yourapikey", "your_api_key", "yourtoken", "your_token",
    "testpassword", "testtoken", "testsecret", "dummy", "fakekey", "fake",
    "notarealsecret", "notarealkey", "sample", "foobar", "foo", "bar",
}


def _is_weak_placeholder_secret_value(value: str) -> bool:
    normalized = re.sub(r"[\s_\-]", "", value).lower()
    # strip a trailing digit run too -- "changeme123", "testpassword1" are
    # still the same placeholder word with a throwaway numeric suffix.
    core = re.sub(r"\d+$", "", normalized)
    if normalized in _WEAK_SECRET_VALUES or core in _WEAK_SECRET_VALUES:
        return True
    # a run of the same character (xxxxxxxx, 00000000) is a placeholder shape
    if len(set(normalized)) <= 1:
        return True
    return False
_RE_EVAL_PY = re.compile(r"\b(eval|exec)\s*\(")
_RE_EVAL_JS = re.compile(r"\beval\s*\(")
_RE_BARE_EXCEPT = re.compile(r"^\s*except\s*:\s*$", re.MULTILINE)
_RE_EMPTY_CATCH_JS = re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}")
# ponytail: spec's literal pattern (`...["'][^"'\n]*(\+|\{)`) only matches concatenation
# where + is OUTSIDE the string (e.g. "..." + var) — it can't match an f-string brace
# because that brace sits BEFORE the closing quote, not after it. Added a second
# alternative so the documented f-string case (f"SELECT ... {var}") actually fires too.
_RE_SQL_CONCAT = re.compile(
    # Third alternative added after the python50 benchmark exposed a real
    # false negative: the single most common SQL-injection shape puts the
    # interpolation inside SQL string quoting -- f"... WHERE name = '{name}'".
    # The first two alternatives both stop at the inner quote (their
    # character classes exclude quotes), so that case never matched. The
    # third allows quotes between the SQL keyword and the interpolation.
    r"(?i)(select|insert|update|delete)\b(?:"
    r"[^\"'\n]*(?:[\"'][^\"'\n]*\+|\{[^{}\"'\n]*\}[^\"'\n]*[\"'])"
    r"|[^\n]*\{[^{}\n]+\}"
    r")"
)
# GOD spec Rule 2 requires evidence of the full path: untrusted source ->
# propagation -> unsafe SQL construction -> DATABASE EXECUTION SINK. The
# pattern above only detects the "unsafe SQL construction" step -- without
# a sink requirement, ANY string starting with select/insert/update/delete
# that gets concatenated fires, including plain English strings that
# happen to start with one of those words and have nothing to do with a
# database at all (e.g. msg = "SELECT this: " + name). Require a real SQL
# execution call nearby before treating the construction as a finding.
_RE_SQL_EXECUTION_SINK = re.compile(r"\.\s*execute(?:many|script)?\s*\(|\braw\s*\(")
_RE_TLS_NODE = re.compile(r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0")
_RE_UNSAFE_DESERIALIZE_JS = re.compile(r"node-serialize|\bunserialize\s*\(")
_RE_TODO = re.compile(r"(?i)#\s*(TODO|FIXME)|//\s*(TODO|FIXME)")
_RE_WEAK_CRYPTO_PY = re.compile(r"\b(hashlib\.(md5|sha1)\s*\(|Crypto\.Hash\.(MD5|SHA1)\b)")
_RE_WEAK_CRYPTO_JS = re.compile(r"\bcreateHash\s*\(\s*['\"](md5|sha1)['\"]\s*\)")
_RE_INSECURE_RANDOM_PY = re.compile(r"\brandom\.(random|randint|choice|choices|randrange)\s*\(")
_RE_INSECURE_RANDOM_JS = re.compile(r"\bMath\.random\s*\(")
_RE_SECURITY_TOKEN_WORD = re.compile(r"(?i)(token|secret|password|api[_-]?key|session|reset|otp|nonce)")
# Phase 3.3: a NoSQL finding needs both a recognized database receiver and a
# direct, attacker-controlled *object* used as its filter. A bare `.find()` is
# not enough: it could be an Array/String/application helper. Likewise,
# `{email: req.body.email}` is a deliberate scalar lookup, not raw operator
# injection. Broader propagation is deferred to Phase 4.
_RE_NOSQL_DIRECT_FILTER_JS = re.compile(
    r"(?P<receiver>"
    r"(?:\b(?:db|mongo|mongoose)\b(?:\.[A-Za-z_$][\w$]*)+"
    r"|\b[A-Z][A-Za-z0-9_$]*\b"
    r"|\b[A-Za-z_$][\w$]*(?:Collection|Model)\b)"
    r")\.(?P<method>find|findOne|findMany|findOneAndUpdate|"
    r"updateOne|updateMany|deleteOne|deleteMany)\s*\(\s*"
    r"(?P<source>(?:req|request)\.(?:body|query))\b"
)
_RE_NOSQL_DIRECT_FILTER_PY = re.compile(
    r"(?P<receiver>"
    r"(?:\b(?:db|mongo|database)\b(?:\.[A-Za-z_]\w*)+"
    r"|\b(?:self\.)?[A-Za-z_]\w*(?:_collection|_repo(?:sitory)?)\b"
    r"|\bcollection\b)"
    r")\.(?P<method>find_one|find|find_many|find_one_and_update|"
    r"update_one|update_many|delete_one|delete_many)\s*\(\s*"
    r"(?P<source>request\.(?:json|args)|request\.get_json\s*\([^)]*\)|req\.(?:json|args))"
)
_RE_ARCHIVE_EXTRACT_PY = re.compile(r"\b(zipfile\.)?ZipFile\s*\([^)]*\)\.extractall\s*\(|\.extractall\s*\(")
_RE_ARCHIVE_EXTRACT_JS = re.compile(r"\bextractAllTo\s*\([^)]*(req\.|request\.)")
_RE_XSS_JS = re.compile(r"\b(innerHTML|outerHTML)\s*=\s*[^;]*(req\.|request\.|props\.|state\.|location\.|document\.location)")
_RE_REACT_DANGEROUS_HTML = re.compile(r"dangerouslySetInnerHTML\s*=\s*\{\s*\{[^}]*(__html|html)\s*:")
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
_RE_JS_AUTH_COOKIE = re.compile(
    r"\b(?:res|response)\.cookie\s*\(\s*['\"](?P<name>[^'\"]*(?:auth|session|token|jwt)[^'\"]*)['\"]\s*,"
    r"[^,{}]+\s*,\s*\{(?P<options>[^{}]*)\}",
    re.IGNORECASE,
)
_RE_JS_NUMERIC_COERCION_DEFAULT = re.compile(r"\bNumber\s*\([^)]*\)\s*\|\|\s*0\b")
_RE_JS_DATE_SLICE = re.compile(r"\.\s*(date|createdAt|updatedAt)\s*\.slice\s*\(")
_RE_JS_PERCENT_ZERO_BASELINE = re.compile(r"if\s*\(\s*!\s*(previous|prev|oldValue|baseline)\s*\)\s*return\s+0\s*;")
_RE_JS_UNKNOWN_TYPE_DEFAULT = re.compile(r"if\s*\([^)]*\.type\s*={2,3}\s*['\"][^'\"]+['\"][^)]*\)\s*\{[^{}]*\}\s*else\s*\{", re.DOTALL)
_RE_PLAINTEXT_PASSWORD_PY = re.compile(r"password\s*=\s*(request\.(json|form)|req\.(json|form)|input\s*\()", re.IGNORECASE)
_RE_PLAINTEXT_PASSWORD_JS = re.compile(r"(password)\s*=\s*(req\.body|request\.body)", re.IGNORECASE)
_RE_MONGOOSE_MONEY_NUMBER = re.compile(
    r"(?i)\b(balance|amount|price|total|subtotal|credit|debit|fee|cost)\w*\s*:\s*\{[^{}]*type\s*:\s*Number(?![^{}]*(min\s*:|validate\s*:))[^{}]*\}"
)
_RE_PROCESS_GLOBAL_AUTH_CACHE = re.compile(
    r"(?s)\b(?:let|var)\s+(?:cachedUser|currentUser)\b.*?\b(?:req|request)\.user\s*="
)
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
    "path_traversal_file": {"title": "Request-controlled path reaches file operation", "languages": ["python"], "category": "security"},
    "unsafe_archive_extract": {"title": "Archive extraction without containment", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "ssrf_untrusted_url": {"title": "Outbound request to untrusted URL", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "xss_unsafe_html_sink": {"title": "Unsafe HTML rendering sink", "languages": ["javascript", "typescript"], "category": "security"},
    "react_dangerous_html": {"title": "React dangerouslySetInnerHTML", "languages": ["javascript", "typescript"], "category": "security"},
    "permissive_cors": {"title": "Permissive wildcard CORS", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "debug_config_enabled": {"title": "Debug/development config enabled", "languages": ["python", "javascript", "typescript"], "category": "best_practice"},
    "weak_crypto_hash": {"title": "Weak cryptographic hash", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "insecure_random_secret": {"title": "Insecure randomness for secret-like value", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "jwt_signature_verification_disabled": {"title": "JWT signature verification disabled", "languages": ["python"], "category": "security"},
    "jwt_algorithm_verification_bypass": {"title": "JWT algorithm verification bypass", "languages": ["python"], "category": "security"},
    "insecure_auth_cookie": {"title": "Insecure authentication cookie configuration", "languages": ["python"], "category": "security"},
    "jwt_insecure_secret_fallback": {"title": "JWT secret has a literal fallback", "languages": ["python"], "category": "security"},
    "sensitive_logging": {"title": "Sensitive data written to logs", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "blocking_call_in_async": {"title": "Blocking call inside async handler/function", "languages": ["python", "javascript", "typescript"], "category": "performance"},
    "unsafe_tempfile": {"title": "Unsafe temporary file name generation", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "unsafe_redirect": {"title": "Redirect target controlled by request input", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "frontend_token_storage": {"title": "Auth token stored in browser storage", "languages": ["javascript", "typescript"], "category": "security"},
    "plaintext_password_handling": {"title": "Plaintext password read without hashing evidence", "languages": ["python", "javascript", "typescript"], "category": "security"},
    "mongoose_money_number_no_validation": {"title": "Monetary Number field lacks validation", "languages": ["javascript", "typescript"], "category": "data_integrity"},
    "js_numeric_coercion_default": {"title": "Silent numeric coercion to zero", "languages": ["javascript", "typescript"], "category": "logic"},
    "js_date_slice_without_validation": {"title": "Date slicing without visible validation", "languages": ["javascript", "typescript"], "category": "logic"},
    "js_zero_baseline_fallback": {"title": "Zero baseline treated as missing", "languages": ["javascript", "typescript"], "category": "logic"},
    "js_unknown_type_default": {"title": "Unknown enum/type falls into default branch", "languages": ["javascript", "typescript"], "category": "logic"},
    "process_global_auth_cache": {"title": "Process-global authentication cache", "languages": ["javascript", "typescript"], "category": "security"},
}

RULE_FIX_SUGGESTIONS = {
    "sensitive_logging": "Do not log token, password, secret, or API-key values. Log a stable non-sensitive event or redacted identifier instead.",
    "hardcoded_secret": "Move the credential into a secret manager or environment variable and rotate the exposed value.",
    "sql_concat": "Use parameterized query APIs instead of concatenating or interpolating request-controlled values.",
    "nosql_untrusted_filter": "Build an allowlisted query object from approved fields instead of passing request-controlled objects directly.",
    "subprocess_shell_true": "Avoid shell=True and pass an argument array; validate any request-controlled argument against an allowlist.",
    "os_system_call": "Replace shell execution with a safe library call or fixed command plus allowlisted arguments.",
    "ssrf_untrusted_url": "Validate outbound URLs against an allowlist and block private/internal network targets before making the request.",
    "path_traversal_file": "Resolve the requested path under a fixed base directory and reject paths that escape it.",
    "unsafe_archive_extract": "Validate archive member paths before extraction and reject entries that escape the destination directory.",
    "unsafe_deserialization": "Use a safe parser/loader for untrusted input and avoid object deserialization APIs.",
    "dangerous_eval": "Replace dynamic code execution with a safe parser or explicit command dispatch table.",
    "tls_verification_disabled": "Keep TLS certificate verification enabled and configure trusted CA material explicitly when needed.",
    "permissive_cors": "Use an explicit origin allowlist and do not combine wildcard origins with credentials.",
    "weak_crypto_hash": "Use a modern password hashing or cryptographic primitive appropriate to the security boundary.",
    "insecure_random_secret": "Use a cryptographically secure random source such as Python secrets or Node crypto for token generation.",
    "frontend_token_storage": "Keep auth tokens out of localStorage/sessionStorage; prefer HttpOnly secure cookies or in-memory state.",
}

# language-gated pattern tables for the 3 checks that only covered Python
# before this — Java/C++ intentionally absent, out of scope.
EMPTY_CATCH_PATTERNS = {
    "python": _RE_BARE_EXCEPT,
    "javascript": _RE_EMPTY_CATCH_JS,
    "typescript": _RE_EMPTY_CATCH_JS,
}
DESERIALIZATION_PATTERNS = {
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
                "fix_suggestion": RULE_FIX_SUGGESTIONS.get(rule, "Review the deterministic evidence and apply the matching secure pattern."),
                "source": "deterministic",
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
        "fix_suggestion": RULE_FIX_SUGGESTIONS.get(rule, "Review the deterministic evidence and apply the matching secure pattern."),
        "source": "deterministic",
    }


def _guarded_findings(content: str, path: str, pattern: re.Pattern, rule: str, severity: str, category: str, message: str, guard=None) -> list[dict]:
    findings = []
    for match in pattern.finditer(content):
        if guard and not guard(content, match):
            continue
        findings.append(_finding(path, content, match, rule, severity, category, message))
    return findings


# A non-secret marker word that is part of a hostname (example.com,
# example.invalid, sample.org) says nothing about whether a nearby
# credential assignment is real -- placeholder domains are extremely
# common in otherwise-production code. Stripped before the context check.
_RE_MARKER_IN_HOSTNAME = re.compile(
    r"(?i)\b(example|sample|dummy|fake|placeholder)\.[a-z]{2,}\b"
)


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
    # Drop placeholder-domain occurrences first, so a URL like
    # "https://example.invalid/users" can't suppress a genuine adjacent
    # credential (real false negative found by the python50 benchmark).
    nearby = _RE_MARKER_IN_HOSTNAME.sub("", nearby)
    return bool(_NON_SECRET_CONTEXT.search(nearby))


def _security_context_guard(content: str, match: re.Match) -> bool:
    line_start, line_end = _line_bounds(content, match.start(), match.end())
    previous_start = content.rfind("\n", 0, max(0, line_start - 1)) + 1
    previous_start = content.rfind("\n", 0, max(0, previous_start - 1)) + 1
    return bool(_HASH_SECURITY_CONTEXT.search(content[previous_start:line_end]))


def _sql_execution_sink_guard(content: str, match: re.Match) -> bool:
    return bool(_RE_SQL_EXECUTION_SINK.search(_nearby(content, match.start(), match.end(), radius=250)))


def _secret_random_guard(content: str, match: re.Match) -> bool:
    line_start, line_end = _line_bounds(content, match.start(), match.end())
    previous_start = content.rfind("\n", 0, max(0, line_start - 1)) + 1
    previous_start = content.rfind("\n", 0, max(0, previous_start - 1)) + 1
    return bool(_RE_SECURITY_TOKEN_WORD.search(content[previous_start:line_end]))


def _python_security_context_guard(content: str, match: re.Match) -> bool:
    return _outside_python_comment_or_string(content, match) and _security_context_guard(content, match)


def _python_secret_random_guard(content: str, match: re.Match) -> bool:
    return _outside_python_comment_or_string(content, match) and _secret_random_guard(content, match)


def _javascript_security_context_guard(content: str, match: re.Match) -> bool:
    return _outside_javascript_comment_or_string(content, match) and _security_context_guard(content, match)


def _javascript_secret_random_guard(content: str, match: re.Match) -> bool:
    return _outside_javascript_comment_or_string(content, match) and _secret_random_guard(content, match)


def _python_non_code_spans(content: str) -> list[tuple[int, int]]:
    line_offsets = []
    offset = 0
    for line in content.splitlines(keepends=True):
        line_offsets.append(offset)
        offset += len(line)

    def absolute(pos: tuple[int, int]) -> int:
        line, col = pos
        if line <= 0 or line > len(line_offsets):
            return 0
        return line_offsets[line - 1] + col

    spans = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(content).readline):
            if token.type in {tokenize.STRING, tokenize.COMMENT}:
                spans.append((absolute(token.start), absolute(token.end)))
    except tokenize.TokenError:
        return spans
    return spans


def _outside_python_comment_or_string(content: str, match: re.Match) -> bool:
    start = match.start()
    return not any(span_start <= start < span_end for span_start, span_end in _python_non_code_spans(content))


def _javascript_non_code_spans(content: str) -> list[tuple[int, int]]:
    """Small lexical guard for the direct NoSQL detector.

    This is not a JavaScript parser. It only prevents comment and string text
    from becoming executable-looking evidence, which is all this local rule
    needs before dedicated JS AST support is introduced in Phase 5.
    """
    spans = []
    index = 0
    length = len(content)
    while index < length:
        if content.startswith("//", index):
            end = content.find("\n", index)
            spans.append((index, length if end == -1 else end))
            index = length if end == -1 else end
            continue
        if content.startswith("/*", index):
            end = content.find("*/", index + 2)
            end = length if end == -1 else end + 2
            spans.append((index, end))
            index = end
            continue
        if content[index] in {"'", '"', "`"}:
            quote = content[index]
            end = index + 1
            while end < length:
                if content[end] == "\\":
                    end += 2
                    continue
                if content[end] == quote:
                    end += 1
                    break
                end += 1
            spans.append((index, min(end, length)))
            index = end
            continue
        index += 1
    return spans


def _outside_javascript_comment_or_string(content: str, match: re.Match) -> bool:
    start = match.start()
    return not any(span_start <= start < span_end for span_start, span_end in _javascript_non_code_spans(content))


def _nosql_direct_filter_findings(content: str, path: str, language: str) -> list[dict]:
    if language == "python":
        pattern = _RE_NOSQL_DIRECT_FILTER_PY
        is_code = _outside_python_comment_or_string
    elif language in {"javascript", "typescript"}:
        pattern = _RE_NOSQL_DIRECT_FILTER_JS
        is_code = _outside_javascript_comment_or_string
    else:
        return []

    findings = []
    for match in pattern.finditer(content):
        if is_code(content, match):
            findings.append(
                _finding(
                    path,
                    content,
                    match,
                    "nosql_untrusted_filter",
                    "high",
                    "security",
                    "Request-controlled object is passed directly as a recognized NoSQL query filter",
                )
            )
    return findings


def _ast_finding(path: str, content: str, node: ast.AST, rule: str, message: str) -> dict:
    evidence = ast.get_source_segment(content, node) or "command execution call"
    return {
        "file": path,
        "line": getattr(node, "lineno", 1),
        "rule": rule,
        "severity": "high",
        "category": "security",
        "message": message,
        "evidence": evidence[:120],
        "confidence": "medium",
        "evidence_type": "deterministic_pattern",
        "fix_suggestion": RULE_FIX_SUGGESTIONS.get(rule, "Review the deterministic evidence and apply the matching secure pattern."),
        "source": "deterministic",
    }


def _python_request_controlled(expression: ast.AST, tainted_names: set[str]) -> bool:
    """Return true only for direct or locally-propagated request input."""
    if isinstance(expression, ast.Name):
        return expression.id in {"request", "req"} or expression.id in tainted_names
    if isinstance(expression, ast.Subscript):
        return _python_request_controlled(expression.value, tainted_names)
    if isinstance(expression, ast.Attribute):
        return _python_request_controlled(expression.value, tainted_names)
    if isinstance(expression, ast.Call):
        if isinstance(expression.func, ast.Name) and expression.func.id == "input":
            return True
        return any(_python_request_controlled(argument, tainted_names) for argument in expression.args)
    if isinstance(expression, ast.JoinedStr):
        return any(
            isinstance(value, ast.FormattedValue)
            and _python_request_controlled(value.value, tainted_names)
            for value in expression.values
        )
    if isinstance(expression, ast.BinOp):
        return _python_request_controlled(expression.left, tainted_names) or _python_request_controlled(expression.right, tainted_names)
    if isinstance(expression, (ast.List, ast.Tuple, ast.Set)):
        return any(_python_request_controlled(element, tainted_names) for element in expression.elts)
    if isinstance(expression, ast.Dict):
        return any(_python_request_controlled(value, tainted_names) for value in expression.values)
    return False


def _python_assignment_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for element in node.elts for name in _python_assignment_names(element)]
    return []


def _python_command_injection_findings(content: str, path: str) -> list[dict]:
    """Detect direct/local attacker flow to supported command execution APIs."""
    if not any(marker in content for marker in ("subprocess", "os.system", "os.popen")):
        return []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    subprocess_modules = {"subprocess"}
    os_modules = {"os"}
    subprocess_functions = set()
    os_functions = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    subprocess_modules.add(alias.asname or alias.name)
                elif alias.name == "os":
                    os_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "subprocess":
                subprocess_functions.update(alias.asname or alias.name for alias in node.names)
            elif node.module == "os":
                os_functions.update(alias.asname or alias.name for alias in node.names)

    tainted_names: set[str] = set()
    findings = []
    command_methods = {"run", "Popen", "call", "check_call", "check_output"}
    os_methods = {"system", "popen"}
    ordered_nodes = sorted(ast.walk(tree), key=lambda node: (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)))
    for node in ordered_nodes:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is not None and _python_request_controlled(value, tainted_names):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    tainted_names.update(_python_assignment_names(target))
            continue
        if not isinstance(node, ast.Call) or not node.args:
            continue

        rule = None
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            receiver = node.func.value.id
            if receiver in subprocess_modules and node.func.attr in command_methods:
                rule = "subprocess_shell_true"
            elif receiver in os_modules and node.func.attr in os_methods:
                rule = "os_system_call"
        elif isinstance(node.func, ast.Name):
            if node.func.id in subprocess_functions:
                rule = "subprocess_shell_true"
            elif node.func.id in os_functions:
                rule = "os_system_call"
        if rule is None:
            continue

        shell_enabled = any(
            keyword.arg == "shell"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        )
        if shell_enabled or any(_python_request_controlled(argument, tainted_names) for argument in node.args):
            findings.append(
                _ast_finding(
                    path,
                    content,
                    node,
                    rule,
                    "Attacker-controlled data reaches a supported OS command execution API",
                )
            )
    return findings


_RE_JS_CHILD_PROCESS_REQUIRE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*require\s*\(\s*['\"]child_process['\"]\s*\)"
)
_RE_JS_CHILD_PROCESS_NAMESPACE_IMPORT = re.compile(
    r"\bimport\s+\*\s+as\s+(?P<name>[A-Za-z_$][\w$]*)\s+from\s+['\"]child_process['\"]"
)
_RE_JS_CHILD_PROCESS_DEFAULT_IMPORT = re.compile(
    r"\bimport\s+(?P<name>[A-Za-z_$][\w$]*)\s+from\s+['\"]child_process['\"]"
)
_RE_JS_CHILD_PROCESS_FUNCTION_ALIAS = re.compile(
    r"\b(?:const|let|var)\s*\{(?P<body>[^}]+)\}\s*=\s*require\s*\(\s*['\"]child_process['\"]\s*\)"
    r"|\bimport\s*\{(?P<imports>[^}]+)\}\s*from\s*['\"]child_process['\"]"
)
_RE_JS_ASSIGNMENT = re.compile(r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<value>[^;\n]+)")
_RE_JS_COMMAND_CALL = re.compile(r"(?P<callee>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(")
_RE_JS_REQUEST_SOURCE = re.compile(r"\b(?:req|request)\.(?:body|query|params)\b")


def _javascript_call_arguments(content: str, opening_paren: int) -> tuple[str, int] | None:
    depth = 0
    index = opening_paren
    quote = None
    while index < len(content):
        char = content[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return content[opening_paren + 1:index], index + 1
        index += 1
    return None


def _javascript_command_injection_findings(content: str, path: str) -> list[dict]:
    """Local source-to-sink command checks for Node's child_process APIs."""
    module_aliases = {"child_process"}
    function_aliases = {}
    for pattern in (
        _RE_JS_CHILD_PROCESS_REQUIRE,
        _RE_JS_CHILD_PROCESS_NAMESPACE_IMPORT,
        _RE_JS_CHILD_PROCESS_DEFAULT_IMPORT,
    ):
        module_aliases.update(match.group("name") for match in pattern.finditer(content))
    for match in _RE_JS_CHILD_PROCESS_FUNCTION_ALIAS.finditer(content):
        aliases = match.group("body") or match.group("imports") or ""
        for entry in aliases.split(","):
            pieces = re.split(r"\s+as\s+|\s*:\s*", entry.strip())
            original = pieces[0].strip()
            alias = pieces[-1].strip()
            if original in {"exec", "execSync", "spawn", "spawnSync"}:
                function_aliases[alias] = original

    tainted_names: set[str] = set()
    for match in _RE_JS_ASSIGNMENT.finditer(content):
        if not _outside_javascript_comment_or_string(content, match):
            continue
        value = match.group("value")
        if _RE_JS_REQUEST_SOURCE.search(value) or any(re.search(rf"\b{re.escape(name)}\b", value) for name in tainted_names):
            tainted_names.add(match.group("name"))

    findings = []
    seen_starts = set()
    for match in _RE_JS_COMMAND_CALL.finditer(content):
        if not _outside_javascript_comment_or_string(content, match):
            continue
        callee = match.group("callee")
        receiver, dot, method = callee.partition(".")
        if dot:
            supported = receiver in module_aliases and method in {"exec", "execSync", "spawn", "spawnSync"}
        else:
            supported = callee in function_aliases
            method = function_aliases.get(callee, "")
        if not supported or match.start() in seen_starts:
            continue
        opening_paren = content.find("(", match.start(), match.end())
        parsed = _javascript_call_arguments(content, opening_paren)
        if parsed is None:
            continue
        arguments, end = parsed
        shell_enabled = bool(re.search(r"\bshell\s*:\s*true\b", arguments))
        command_is_shell_string = method in {"exec", "execSync"}
        arguments_are_untrusted = _RE_JS_REQUEST_SOURCE.search(arguments) or any(
            re.search(rf"\b{re.escape(name)}\b", arguments) for name in tainted_names
        )
        if not (shell_enabled or command_is_shell_string or arguments_are_untrusted):
            continue
        seen_starts.add(match.start())
        rule = "spawn_shell_true" if method in {"spawn", "spawnSync"} else "subprocess_shell_true"
        findings.append(
            {
                "file": path,
                "line": _line_of(content, match.start()),
                "rule": rule,
                "severity": "high",
                "category": "security",
                "message": "Attacker-controlled data reaches a supported OS command execution API",
                "evidence": content[match.start():end][:120],
                "confidence": "medium",
                "evidence_type": "deterministic_pattern",
            }
        )
    return findings


def _command_injection_findings(content: str, path: str, language: str) -> list[dict]:
    if language == "python":
        return _python_command_injection_findings(content, path)
    if language in {"javascript", "typescript"}:
        return _javascript_command_injection_findings(content, path)
    return []


def _ast_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _ast_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _python_ssrf_controlled(expression: ast.AST, tainted_names: set[str]) -> bool:
    if isinstance(expression, ast.Name):
        return expression.id in {"request", "req"} or expression.id in tainted_names
    if isinstance(expression, (ast.Attribute, ast.Subscript)):
        return _python_ssrf_controlled(expression.value, tainted_names)
    if isinstance(expression, ast.Call):
        return _python_ssrf_controlled(expression.func, tainted_names) or any(
            _python_ssrf_controlled(argument, tainted_names) for argument in expression.args
        )
    if isinstance(expression, ast.JoinedStr):
        return any(
            isinstance(value, ast.FormattedValue)
            and _python_ssrf_controlled(value.value, tainted_names)
            for value in expression.values
        )
    if isinstance(expression, ast.BinOp):
        return _python_ssrf_controlled(expression.left, tainted_names) or _python_ssrf_controlled(expression.right, tainted_names)
    return False


def _python_fixed_host_destination(expression: ast.AST) -> bool:
    """Recognize a server-controlled host with only a variable path/query."""
    if isinstance(expression, ast.JoinedStr) and expression.values:
        first = expression.values[0]
        return isinstance(first, ast.Constant) and isinstance(first.value, str) and bool(
            re.match(r"https?://[^/?#]+(?:[/?#]|$)", first.value)
        )
    if isinstance(expression, ast.BinOp) and isinstance(expression.left, ast.Constant) and isinstance(expression.left.value, str):
        return bool(re.match(r"https?://[^/?#]+(?:[/?#]|$)", expression.left.value))
    return False


def _static_string_collection_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, (ast.List, ast.Set, ast.Tuple)):
            continue
        if not value.elts or not all(isinstance(element, ast.Constant) and isinstance(element.value, str) for element in value.elts):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            names.update(_python_assignment_names(target))
    return names


def _allowlist_guarded_names(statement: ast.If, allowlist_names: set[str]) -> set[str]:
    if not any(isinstance(item, (ast.Return, ast.Raise)) for item in statement.body):
        return set()
    test = statement.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or not isinstance(test.ops[0], ast.NotIn):
        return set()
    if not isinstance(test.left, ast.Name) or len(test.comparators) != 1 or not isinstance(test.comparators[0], ast.Name):
        return set()
    return {test.left.id} if test.comparators[0].id in allowlist_names else set()


def _python_http_aliases(tree: ast.Module) -> tuple[dict[str, str], dict[str, str]]:
    modules = {"requests": "requests", "httpx": "httpx", "aiohttp": "aiohttp", "urllib": "urllib"}
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in modules:
                    modules[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module in {"requests", "httpx", "aiohttp"}:
                for alias in node.names:
                    functions[alias.asname or alias.name] = f"{node.module}.{alias.name}"
            elif node.module == "urllib.request":
                for alias in node.names:
                    functions[alias.asname or alias.name] = f"urllib.request.{alias.name}"
    return modules, functions


def _python_http_url_argument(call: ast.Call, canonical_name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg in {"url", "uri"}:
            return keyword.value
    if canonical_name.endswith(".request"):
        return call.args[1] if len(call.args) >= 2 else None
    return call.args[0] if call.args else None


def _python_ssrf_sink_name(call: ast.Call, modules: dict[str, str], functions: dict[str, str]) -> str:
    raw = _ast_name(call.func)
    if raw in functions:
        return functions[raw]
    parts = raw.split(".")
    if len(parts) == 2 and parts[0] in modules:
        return f"{modules[parts[0]]}.{parts[1]}"
    if raw == "urllib.request.urlopen":
        return raw
    return ""


def _python_url_like_parameter_names(parameters: list[ast.arg]) -> set[str]:
    url_names = {"url", "uri", "target_url", "webhook_url", "callback_url"}
    return {parameter.arg for parameter in parameters if parameter.arg.lower() in url_names}


def _python_exposed_url_function_name(name: str) -> bool:
    lowered = name.lower()
    return any(
        marker in lowered
        for marker in ("preview", "proxy", "webhook", "callback", "fetch_url", "open_url", "download")
    )


def _python_ssrf_scope_findings(
    statements: list[ast.stmt],
    content: str,
    path: str,
    initial_tainted: set[str],
    allowlist_names: set[str],
    modules: dict[str, str],
    functions: dict[str, str],
) -> list[dict]:
    tainted_names = set(initial_tainted)
    validated_names: set[str] = set()
    findings = []
    methods = {"get", "post", "put", "patch", "delete", "request", "urlopen"}
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(statement, ast.If):
            validated_names.update(_allowlist_guarded_names(statement, allowlist_names))
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            value = statement.value
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            for target in targets:
                for name in _python_assignment_names(target):
                    if value is not None and _python_ssrf_controlled(value, tainted_names) and not _python_fixed_host_destination(value):
                        tainted_names.add(name)
                    else:
                        tainted_names.discard(name)
                        validated_names.discard(name)
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue
            canonical_name = _python_ssrf_sink_name(node, modules, functions)
            if not canonical_name or canonical_name.rsplit(".", 1)[-1] not in methods:
                continue
            url = _python_http_url_argument(node, canonical_name)
            if url is None or _python_fixed_host_destination(url):
                continue
            if isinstance(url, ast.Name) and url.id in validated_names:
                continue
            if _python_ssrf_controlled(url, tainted_names):
                findings.append(
                    _ast_finding(
                        path,
                        content,
                        node,
                        "ssrf_untrusted_url",
                        "Attacker-controlled URL reaches a supported outbound HTTP client",
                    )
                )
    return findings


def _python_ssrf_findings(content: str, path: str) -> list[dict]:
    if not any(marker in content for marker in ("requests", "httpx", "aiohttp", "urllib", "urlopen(")):
        return []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    allowlist_names = _static_string_collection_names(tree)
    modules, functions = _python_http_aliases(tree)
    findings = _python_ssrf_scope_findings(tree.body, content, path, set(), allowlist_names, modules, functions)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_route_handler = any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr in {"get", "post", "put", "patch", "delete", "route", "api_route"}
            for decorator in node.decorator_list
        )
        parameters = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        parameter_names = {parameter.arg for parameter in parameters if parameter.arg in {"request", "req"}}
        if is_route_handler or _python_exposed_url_function_name(node.name):
            parameter_names.update(_python_url_like_parameter_names(parameters))
        if not parameter_names:
            continue
        findings.extend(
            _python_ssrf_scope_findings(node.body, content, path, parameter_names, allowlist_names, modules, functions)
        )
    return findings


_RE_JS_HTTP_CALL = re.compile(r"(?P<callee>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(")


def _javascript_fixed_host_destination(arguments: str) -> bool:
    return bool(re.match(r"\s*[`'\"]https?://[^/?#]+(?:[/?#]|$)", arguments))


def _javascript_ssrf_findings(content: str, path: str) -> list[dict]:
    tainted_names: set[str] = set()
    for match in _RE_JS_ASSIGNMENT.finditer(content):
        if not _outside_javascript_comment_or_string(content, match):
            continue
        value = match.group("value")
        if _RE_JS_REQUEST_SOURCE.search(value) or any(re.search(rf"\b{re.escape(name)}\b", value) for name in tainted_names):
            if not _javascript_fixed_host_destination(value):
                tainted_names.add(match.group("name"))

    findings = []
    supported_methods = {"get", "post", "put", "patch", "delete", "request"}
    for match in _RE_JS_HTTP_CALL.finditer(content):
        if not _outside_javascript_comment_or_string(content, match):
            continue
        callee = match.group("callee")
        receiver, dot, method = callee.partition(".")
        supported = callee == "fetch" or (dot and receiver in {"axios", "got", "request"} and method in supported_methods)
        if not supported:
            continue
        parsed = _javascript_call_arguments(content, match.end() - 1)
        if parsed is None:
            continue
        arguments, end = parsed
        if _javascript_fixed_host_destination(arguments):
            continue
        if not (_RE_JS_REQUEST_SOURCE.search(arguments) or any(re.search(rf"\b{re.escape(name)}\b", arguments) for name in tainted_names)):
            continue
        findings.append(
            {
                "file": path,
                "line": _line_of(content, match.start()),
                "rule": "ssrf_untrusted_url",
                "severity": "high",
                "category": "security",
                "message": "Attacker-controlled URL reaches a supported outbound HTTP client",
                "evidence": content[match.start():end][:120],
                "confidence": "medium",
                "evidence_type": "deterministic_pattern",
            }
        )
    return findings


def _ssrf_findings(content: str, path: str, language: str) -> list[dict]:
    if language == "python":
        return _python_ssrf_findings(content, path)
    if language in {"javascript", "typescript"}:
        return _javascript_ssrf_findings(content, path)
    return []


def _python_static_root(expression: ast.AST, root_names: set[str]) -> bool:
    if isinstance(expression, ast.Name):
        return expression.id in root_names
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return expression.value.startswith(("/", "\\"))
    if isinstance(expression, ast.Call) and _ast_name(expression.func) in {"Path", "pathlib.Path"} and expression.args:
        return _python_static_root(expression.args[0], root_names)
    return False


def _python_path_risky(expression: ast.AST, tainted_names: set[str], root_names: set[str], filename_names: set[str]) -> bool:
    if _python_ssrf_controlled(expression, tainted_names):
        return True
    if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Div):
        return _python_static_root(expression.left, root_names) and isinstance(expression.right, ast.Name) and expression.right.id in filename_names
    if isinstance(expression, ast.Call):
        return any(_python_path_risky(argument, tainted_names, root_names, filename_names) for argument in expression.args)
    return False


def _path_guarded_names(statement: ast.If, root_names: set[str]) -> set[str]:
    """Recognize ``if ROOT not in target.parents: raise/return`` containment."""
    if not any(isinstance(item, (ast.Return, ast.Raise)) for item in statement.body):
        return set()
    test = statement.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or not isinstance(test.ops[0], ast.NotIn):
        return set()
    if not isinstance(test.left, ast.Name) or test.left.id not in root_names or len(test.comparators) != 1:
        return set()
    comparator = test.comparators[0]
    if isinstance(comparator, ast.Attribute) and comparator.attr == "parents" and isinstance(comparator.value, ast.Name):
        return {comparator.value.id}
    return set()


def _python_path_sink_argument(call: ast.Call) -> ast.AST | None:
    name = _ast_name(call.func)
    if name in {"open", "os.open", "os.remove", "os.unlink", "os.mkdir", "os.makedirs", "send_file", "FileResponse"}:
        return call.args[0] if call.args else None
    if name.rsplit(".", 1)[-1] in {"read_text", "read_bytes", "write_text", "write_bytes", "unlink", "mkdir", "rmdir"}:
        return call.func.value if isinstance(call.func, ast.Attribute) else None
    return None


def _python_path_scope_findings(
    statements: list[ast.stmt], content: str, path: str, initial_tainted: set[str], filename_names: set[str], initial_roots: set[str] | None = None
) -> list[dict]:
    root_names = set(initial_roots or ())
    tainted_names = set(initial_tainted)
    validated_names: set[str] = set()
    findings = []
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(statement, ast.If):
            validated_names.update(_path_guarded_names(statement, root_names))
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            value = statement.value
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            for target in targets:
                for name in _python_assignment_names(target):
                    if value is not None and _python_static_root(value, root_names):
                        root_names.add(name)
                    elif value is not None and _python_path_risky(value, tainted_names, root_names, filename_names):
                        tainted_names.add(name)
                    else:
                        tainted_names.discard(name)
                        validated_names.discard(name)
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue
            target = _python_path_sink_argument(node)
            if target is None or (isinstance(target, ast.Name) and target.id in validated_names):
                continue
            if _python_path_risky(target, tainted_names, root_names, filename_names):
                findings.append(
                    _ast_finding(
                        path,
                        content,
                        node,
                        "path_traversal_file",
                        "Attacker-controlled path reaches a supported file operation",
                    )
                )
    return findings


def _python_path_traversal_findings(content: str, path: str) -> list[dict]:
    if not any(marker in content for marker in ("open(", ".read_text(", ".read_bytes(", ".write_text(", ".write_bytes(", "os.remove", "os.unlink", "os.mkdir", "os.makedirs", "send_file(", "FileResponse(")):
        return []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    module_roots = set()
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)) and statement.value is not None and _python_static_root(statement.value, module_roots):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            for target in targets:
                module_roots.update(_python_assignment_names(target))
    findings = _python_path_scope_findings(tree.body, content, path, set(), set(), module_roots)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        parameters = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        request_names = {parameter.arg for parameter in parameters if parameter.arg in {"request", "req"}}
        filename_names = {
            parameter.arg for parameter in parameters if parameter.arg.lower() in {"filename", "file_name", "relative_path"}
        }
        if request_names or filename_names:
            findings.extend(_python_path_scope_findings(node.body, content, path, request_names, filename_names, module_roots))
    return findings


def _path_traversal_findings(content: str, path: str, language: str) -> list[dict]:
    return _python_path_traversal_findings(content, path) if language == "python" else []


def _python_unsafe_deserialization_findings(content: str, path: str) -> list[dict]:
    if "pickle" not in content and "yaml" not in content:
        return []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    pickle_modules = {"pickle"}
    yaml_modules = {"yaml"}
    pickle_functions = set()
    yaml_functions = {}
    safe_loader_names = {"SafeLoader", "BaseLoader"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pickle":
                    pickle_modules.add(alias.asname or alias.name)
                elif alias.name == "yaml":
                    yaml_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "pickle":
                pickle_functions.update(alias.asname or alias.name for alias in node.names)
            elif node.module == "yaml":
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    if alias.name in {"SafeLoader", "BaseLoader"}:
                        safe_loader_names.add(local_name)
                    else:
                        yaml_functions[local_name] = alias.name

    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        rule_match = False
        raw = _ast_name(node.func)
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id in pickle_modules and node.func.attr in {"load", "loads"}:
                rule_match = True
            elif node.func.value.id in yaml_modules and node.func.attr in {"unsafe_load", "load"}:
                if node.func.attr == "unsafe_load":
                    rule_match = True
                else:
                    loaders = [keyword.value for keyword in node.keywords if keyword.arg == "Loader"]
                    if len(node.args) >= 2:
                        loaders.append(node.args[1])
                    rule_match = not any(_ast_name(loader).rsplit(".", 1)[-1] in safe_loader_names for loader in loaders)
        elif isinstance(node.func, ast.Name):
            if node.func.id in pickle_functions:
                rule_match = True
            elif node.func.id in yaml_functions:
                if yaml_functions[node.func.id] == "unsafe_load":
                    rule_match = True
                elif yaml_functions[node.func.id] == "load":
                    loaders = [keyword.value for keyword in node.keywords if keyword.arg == "Loader"]
                    if len(node.args) >= 2:
                        loaders.append(node.args[1])
                    rule_match = not any(_ast_name(loader).rsplit(".", 1)[-1] in safe_loader_names for loader in loaders)
        if rule_match:
            findings.append(
                _ast_finding(
                    path,
                    content,
                    node,
                    "unsafe_deserialization",
                    "Unsafe deserializer is invoked without a safe loader",
                )
            )
    return findings


def _unsafe_deserialization_findings(content: str, path: str, language: str) -> list[dict]:
    return _python_unsafe_deserialization_findings(content, path) if language == "python" else []


def _python_tls_findings(content: str, path: str) -> list[dict]:
    if "verify" not in content or not any(module in content for module in ("requests", "httpx")):
        return []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _ast_name(node.func)
        if name.split(".", 1)[0] not in {"requests", "httpx"}:
            continue
        disabled = any(
            keyword.arg == "verify"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is False
            for keyword in node.keywords
        )
        if disabled:
            findings.append(_ast_finding(path, content, node, "tls_verification_disabled", "TLS certificate verification is disabled for an outbound HTTP client"))
    return findings


def _cors_wildcard_value(value: ast.AST) -> bool:
    if isinstance(value, ast.Constant):
        return value.value == "*"
    return isinstance(value, (ast.List, ast.Tuple, ast.Set)) and any(
        isinstance(element, ast.Constant) and element.value == "*" for element in value.elts
    )


def _python_cors_findings(content: str, path: str) -> list[dict]:
    if "CORS" not in content and "cors" not in content:
        return []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _ast_name(node.func)
        middleware_target = name.endswith(("CORSMiddleware", ".add_middleware")) or name in {"CORS", "cors"}
        if not middleware_target:
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        origin = next((keywords[key] for key in ("allow_origins", "origins", "origin") if key in keywords), None)
        credentials = next((keywords[key] for key in ("allow_credentials", "supports_credentials", "credentials") if key in keywords), None)
        credentialed = isinstance(credentials, ast.Constant) and credentials.value is True
        if origin is not None and credentialed and _cors_wildcard_value(origin):
            findings.append(_ast_finding(path, content, node, "permissive_cors", "Credentialed wildcard CORS configuration exposes authenticated responses cross-origin"))
    return findings


_RE_JS_CORS_CALL = re.compile(r"\bcors\s*\(\s*\{")


def _javascript_cors_findings(content: str, path: str) -> list[dict]:
    findings = []
    for match in _RE_JS_CORS_CALL.finditer(content):
        if not _outside_javascript_comment_or_string(content, match):
            continue
        opening_paren = content.find("(", match.start(), match.end())
        parsed = _javascript_call_arguments(content, opening_paren)
        if parsed is None:
            continue
        arguments, end = parsed
        wildcard = bool(re.search(r"\borigin\s*:\s*['\"]\*['\"]", arguments))
        credentialed = bool(re.search(r"\bcredentials\s*:\s*true\b", arguments))
        if wildcard and credentialed:
            findings.append({
                "file": path, "line": _line_of(content, match.start()), "rule": "permissive_cors",
                "severity": "high", "category": "security",
                "message": "Credentialed wildcard CORS configuration exposes authenticated responses cross-origin",
                "evidence": content[match.start():end][:120], "confidence": "medium", "evidence_type": "deterministic_pattern",
            })
    return findings


def _cors_findings(content: str, path: str, language: str) -> list[dict]:
    if language == "python":
        return _python_cors_findings(content, path)
    if language in {"javascript", "typescript"}:
        return _javascript_cors_findings(content, path)
    return []


_AUTH_COOKIE_NAME = re.compile(r"(?i)(auth|session|token|jwt)")
_AUTH_SECRET_ENV_NAME = re.compile(r"(?i)(jwt|token|session|secret|signing[_-]?key)")


def _constant_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_false_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _keyword_value(call: ast.Call, name: str) -> ast.AST | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _jwt_options_disable_signature(node: ast.AST | None) -> bool:
    if not isinstance(node, ast.Dict):
        return False
    for key, value in zip(node.keys, node.values):
        if _constant_string(key) == "verify_signature" and _is_false_literal(value):
            return True
    return False


def _jwt_allows_none_algorithm(node: ast.AST | None) -> bool:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_constant_string(item) == "none" for item in node.elts)
    return _constant_string(node) == "none"


def _python_auth_session_findings(content: str, path: str) -> list[dict]:
    """Report only literal, executable auth/session misconfigurations."""
    if not any(marker in content.lower() for marker in ("jwt", "getenv", "environ.get", "set_cookie")):
        return []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    jwt_modules = {"jwt"}
    jwt_decode_functions: set[str] = set()
    os_modules = {"os"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "jwt":
                    jwt_modules.add(alias.asname or alias.name)
                elif alias.name == "os":
                    os_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "jwt":
                jwt_decode_functions.update(
                    alias.asname or alias.name for alias in node.names if alias.name == "decode"
                )

    findings = []
    ordered_nodes = sorted(ast.walk(tree), key=lambda node: (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)))
    for node in ordered_nodes:
        if isinstance(node, ast.Call):
            is_jwt_decode = (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in jwt_modules
                and node.func.attr == "decode"
            ) or (isinstance(node.func, ast.Name) and node.func.id in jwt_decode_functions)
            if is_jwt_decode:
                if _jwt_options_disable_signature(_keyword_value(node, "options")):
                    findings.append(_ast_finding(
                        path, content, node, "jwt_signature_verification_disabled",
                        "JWT signature verification is explicitly disabled",
                    ))
                if _jwt_allows_none_algorithm(_keyword_value(node, "algorithms")):
                    findings.append(_ast_finding(
                        path, content, node, "jwt_algorithm_verification_bypass",
                        "JWT decode accepts the unsigned 'none' algorithm",
                    ))

            is_os_getenv = (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in os_modules
                and node.func.attr == "getenv"
            )
            is_environ_get = (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id in os_modules
                and node.func.value.attr == "environ"
            )
            if (is_os_getenv or is_environ_get) and len(node.args) >= 2:
                env_name, fallback = _constant_string(node.args[0]), _constant_string(node.args[1])
                if env_name and fallback is not None and _AUTH_SECRET_ENV_NAME.search(env_name):
                    findings.append(_ast_finding(
                        path, content, node, "jwt_insecure_secret_fallback",
                        "Authentication secret environment variable has a literal fallback",
                    ))

            if isinstance(node.func, ast.Attribute) and node.func.attr == "set_cookie":
                cookie_name = _constant_string(node.args[0]) if node.args else _constant_string(_keyword_value(node, "key"))
                if cookie_name and _AUTH_COOKIE_NAME.search(cookie_name):
                    insecure_flags = [
                        name for name in ("httponly", "secure")
                        if _is_false_literal(_keyword_value(node, name) or ast.Constant(value=True))
                    ]
                    if insecure_flags:
                        findings.append(_ast_finding(
                            path, content, node, "insecure_auth_cookie",
                            f"Authentication cookie explicitly disables {', '.join(insecure_flags)}",
                        ))
    return findings


def _javascript_auth_cookie_findings(content: str, path: str) -> list[dict]:
    findings = []
    for match in _RE_JS_AUTH_COOKIE.finditer(content):
        if not _outside_javascript_comment_or_string(content, match):
            continue
        options = match.group("options")
        insecure_flags = [
            name for name, pattern in (
                ("httpOnly", r"\bhttpOnly\s*:\s*false\b"),
                ("secure", r"\bsecure\s*:\s*false\b"),
            )
            if re.search(pattern, options, re.IGNORECASE)
        ]
        if insecure_flags:
            findings.append(
                _finding(
                    path,
                    content,
                    match,
                    "insecure_auth_cookie",
                    "high",
                    "security",
                    f"Authentication cookie explicitly disables {', '.join(insecure_flags)}",
                )
            )
    return findings


def run_rules(path: str, language: str, content: str) -> list[dict]:
    findings = []

    # 1. hardcoded secret/credential — all languages
    for match in _RE_SECRET.finditer(content):
        if _is_comment_or_non_secret_context(content, match):
            continue
        # The line-based check above only catches a comment/docstring line
        # that itself STARTS with a comment marker -- a secret-shaped
        # example shown inside a multi-line Python docstring (a common
        # documentation pattern) doesn't start with '#' and would slip
        # through. Tokenize-based check catches that: it's real for
        # Python because docstrings are STRING tokens, not comments, so a
        # match landing inside one means it's example text, not live code.
        if language == "python" and not _outside_python_comment_or_string(content, match):
            continue
        if _is_weak_placeholder_secret_value(match.group(2)):
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
        findings += _guarded_findings(
            content, path, _RE_EVAL_PY, "dangerous_eval", "critical", "security",
            "Use of eval/exec on potentially untrusted input", _outside_python_comment_or_string,
        )
    elif language in ("javascript", "typescript"):
        findings += _guarded_findings(
            content, path, _RE_EVAL_JS, "dangerous_eval", "critical", "security",
            "Use of eval/exec on potentially untrusted input", _outside_javascript_comment_or_string,
        )

    # 3. empty / catch-all exception handling — python + js/ts
    pattern = EMPTY_CATCH_PATTERNS.get(language)
    if pattern:
        findings += _findings_for_pattern(
            content, path, pattern, "empty_exception_handler", "medium", "best_practice",
            "Empty or catch-all exception handler silently swallows all errors",
        )

    # 4. SQL string concatenation — all languages. Requires a real SQL
    # execution sink nearby (see _sql_execution_sink_guard) -- otherwise a
    # plain string that merely starts with select/insert/update/delete
    # would fire with no database involved at all.
    findings += _guarded_findings(
        content, path, _RE_SQL_CONCAT, "sql_concat", "critical", "security",
        "Possible SQL injection via string concatenation instead of parameterized query",
        _sql_execution_sink_guard,
    )

    # 5. command injection: only report supported command sinks when direct
    # request/input data reaches the executable or an argument. Static argv or
    # constant command strings are intentionally not command-injection evidence.
    findings += _command_injection_findings(content, path, language)

    # 6. disabled TLS verification — python or node pattern, run both, language-gated
    if language == "python":
        findings += _python_tls_findings(content, path)
    if language in ("javascript", "typescript"):
        findings += _guarded_findings(
            content, path, _RE_TLS_NODE, "tls_verification_disabled", "high", "security",
            "TLS/SSL certificate verification is disabled", _outside_javascript_comment_or_string,
        )

    # 7. unsafe deserialization — python + js/ts
    findings += _unsafe_deserialization_findings(content, path, language)
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
        findings += _javascript_auth_cookie_findings(content, path)
        findings += _nosql_direct_filter_findings(content, path, language)
        findings += _findings_for_pattern(
            content, path, _RE_ARCHIVE_EXTRACT_JS, "unsafe_archive_extract", "high", "security",
            "Archive extraction target is influenced by request input",
        )
        findings += _ssrf_findings(content, path, language)
        findings += _findings_for_pattern(
            content, path, _RE_XSS_JS, "xss_unsafe_html_sink", "high", "security",
            "Request, location, props, or state data is assigned to an HTML sink",
        )
        findings += _findings_for_pattern(
            content, path, _RE_REACT_DANGEROUS_HTML, "react_dangerous_html", "medium", "security",
            "React dangerouslySetInnerHTML is used and needs trusted sanitized HTML evidence",
        )
        findings += _cors_findings(content, path, language)
        findings += _findings_for_pattern(
            content, path, _RE_DEBUG_JS, "debug_config_enabled", "medium", "best_practice",
            "Development/debug configuration appears enabled in source",
        )
        findings += _guarded_findings(
            content, path, _RE_WEAK_CRYPTO_JS, "weak_crypto_hash", "medium", "security",
            "Weak hash algorithm is used in security-adjacent code", _javascript_security_context_guard,
        )
        findings += _guarded_findings(
            content, path, _RE_INSECURE_RANDOM_JS, "insecure_random_secret", "medium", "security",
            "Math.random is used near token/secret generation", _javascript_secret_random_guard,
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
            content, path, _RE_MONGOOSE_MONEY_NUMBER, "mongoose_money_number_no_validation", "medium", "data_integrity",
            "Mongoose monetary Number field has no visible minimum or validation; use Decimal128/cents and validate opening balance/amount values",
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
        findings += _findings_for_pattern(
            content, path, _RE_PROCESS_GLOBAL_AUTH_CACHE, "process_global_auth_cache", "high", "security",
            "Process-global cached identity can assign one user's authentication state to another request; use request-scoped verification or a keyed cache",
        )

    if language == "python":
        findings += _python_auth_session_findings(content, path)
        findings += _nosql_direct_filter_findings(content, path, language)
        findings += _path_traversal_findings(content, path, language)
        findings += _findings_for_pattern(
            content, path, _RE_ARCHIVE_EXTRACT_PY, "unsafe_archive_extract", "high", "security",
            "Archive extraction uses extractall without visible path containment",
        )
        findings += _ssrf_findings(content, path, language)
        findings += _cors_findings(content, path, language)
        findings += _findings_for_pattern(
            content, path, _RE_DEBUG_PY, "debug_config_enabled", "medium", "best_practice",
            "Debug configuration appears enabled in source",
        )
        findings += _guarded_findings(
            content, path, _RE_WEAK_CRYPTO_PY, "weak_crypto_hash", "medium", "security",
            "Weak hash algorithm is used in security-adjacent code", _python_security_context_guard,
        )
        findings += _guarded_findings(
            content, path, _RE_INSECURE_RANDOM_PY, "insecure_random_secret", "medium", "security",
            "random module is used near token/secret generation", _python_secret_random_guard,
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
