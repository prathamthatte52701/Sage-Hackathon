"""Phase 3 basic analyzer: deterministic regex/AST rules over uploaded project files.

No LLM calls here — everything is static analysis so it's fast and free to run
on every project. Per-language extraction lives in services/analyzers/ (one
implementation per language behind a common interface); this module owns
file classification (test/config/deployment) and drives the per-file loop.
"""

from fnmatch import fnmatch
from pathlib import PurePosixPath

from services.analyzers import get_analyzer
from services.analyzers.rules import run_rules

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

        analyzer = get_analyzer(language)
        if analyzer is not None:
            parse_error = analyzer.parse_error_safe(content)
            if parse_error is not None:
                warnings.append(
                    f"{path}: could not parse as valid {analyzer.language.capitalize()} "
                    "(syntax error), skipped import/function extraction"
                )
            else:
                imports = analyzer.extract_imports(content)
                functions = analyzer.extract_functions(content)
                classes = analyzer.extract_classes(content)
                routes = analyzer.extract_routes(content)
                project["imports"].extend({"file": path, "module": m} for m in imports)
                project["functions"].extend({"file": path, "name": n} for n in functions)
                project["classes"].extend({"file": path, "name": n} for n in classes)
                project["apiEndpoints"].extend({"file": path, **route} for route in routes)
        # languages with no registered analyzer (java, cpp, other): no extraction,
        # deterministic pattern rules below still run against their content.

        project["findings"].extend(run_rules(path, language, content))

    # Deduplicate equivalent static findings across rules/analyzers.
    seen = set()
    deduped = []
    for finding in project.get("findings", []):
        key = (finding.get("file"), finding.get("line"), finding.get("rule"), finding.get("evidence"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    project["findings"] = deduped
    return project
