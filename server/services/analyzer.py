"""Phase 3 basic analyzer: deterministic regex/AST rules over uploaded project files.

No LLM calls here — everything is static analysis so it's fast and free to run
on every project.
"""

import ast
import re
from fnmatch import fnmatch
from pathlib import PurePosixPath

SOURCE_LANGUAGES = {"python", "javascript", "typescript", "java", "cpp"}

TEST_FILENAME_PATTERNS = [
    "test_*.py",
    "*_test.py",
    "*.test.js",
    "*.test.jsx",
    "*.test.ts",
    "*.test.tsx",
    "*.spec.js",
    "*.spec.jsx",
    "*.spec.ts",
    "*.spec.tsx",
]
TEST_DIR_NAMES = {"tests", "__tests__"}

CONFIG_FILENAMES = {
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "setup.py",
    "pom.xml",
    "build.gradle",
    ".env.example",
    "tsconfig.json",
}

DEPLOYMENT_FILENAMES = {
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "render.yaml",
    "vercel.json",
    "Procfile",
}

_JS_IMPORT_RE = re.compile(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]")
_JS_REQUIRE_RE = re.compile(r"require\(['\"]([^'\"]+)['\"]\)")


def extract_python_imports(content: str) -> list[str]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                modules.append(node.module)
    return modules


def extract_js_imports(content: str) -> list[str]:
    seen = []
    for pattern in (_JS_IMPORT_RE, _JS_REQUIRE_RE):
        for match in pattern.finditer(content):
            module = match.group(1)
            if module not in seen:
                seen.append(module)
    return seen


def extract_python_definitions(content: str) -> tuple[list[str], list[str]]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return [], []

    functions = []
    classes = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
    return functions, classes


def is_test_file(path: str) -> bool:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if any(part in TEST_DIR_NAMES for part in parts):
        return True
    basename = parts[-1] if parts else path
    return any(fnmatch(basename, pattern) for pattern in TEST_FILENAME_PATTERNS)


def is_config_file(path: str) -> bool:
    basename = PurePosixPath(path.replace("\\", "/")).name
    return basename in CONFIG_FILENAMES


def is_deployment_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    basename = PurePosixPath(normalized).name
    if basename in DEPLOYMENT_FILENAMES:
        return True
    return ".github/workflows/" in normalized


# --- deterministic rule engine -------------------------------------------------

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


def analyze_project(project: dict) -> dict:
    warnings = project.setdefault("warnings", [])

    for file_entry in project.get("files", []):
        path = file_entry["path"]
        language = file_entry.get("language")
        content = file_entry.get("content")

        # filename-only checks: cheap, don't need file content (e.g. requirements.txt,
        # Dockerfile are language="other" and never get content stored, but still need
        # to be classified)
        if is_test_file(path):
            project["tests"].append(path)
        if is_config_file(path):
            project["configs"].append(path)
        if is_deployment_file(path):
            project["deploymentFiles"].append(path)

        if content is None:
            continue

        if language == "python":
            try:
                ast.parse(content)
            except SyntaxError:
                warnings.append(
                    f"{path}: could not parse as valid Python (syntax error), skipped import/function extraction"
                )
            else:
                imports = extract_python_imports(content)
                functions, classes = extract_python_definitions(content)
                project["imports"].extend({"file": path, "module": m} for m in imports)
                project["functions"].extend({"file": path, "name": n} for n in functions)
                project["classes"].extend({"file": path, "name": n} for n in classes)
        elif language in ("javascript", "typescript"):
            imports = extract_js_imports(content)
            project["imports"].extend({"file": path, "module": m} for m in imports)
        # java/cpp: no import/definition extraction (not in scope)

        project["findings"].extend(run_rules(path, language, content))

    return project
