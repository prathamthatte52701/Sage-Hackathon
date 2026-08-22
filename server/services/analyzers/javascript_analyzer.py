# TODO: regex-based, not a real parser - see [decision doc] before treating
# this as equivalent to Python's AST analyzer. A tree-sitter or Babel-subprocess
# upgrade is a separate, explicit decision to make later, not something to
# smuggle into a refactor. Function/class extraction were never implemented
# for JS/TS pre-refactor either - extract_functions/extract_classes return []
# here for the same reason, unchanged behavior, not a regression.

import re

from .base import LanguageAnalyzer

_JS_IMPORT_RE = re.compile(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]")
_JS_REQUIRE_RE = re.compile(r"require\(['\"]([^'\"]+)['\"]\)")
_JS_FUNC_RE = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>")
_JS_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)\b")
_JS_ROUTE_RE = re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]")


class JavaScriptAnalyzer(LanguageAnalyzer):
    language = "javascript"

    def extract_imports(self, content: str) -> list[str]:
        seen = []
        for pattern in (_JS_IMPORT_RE, _JS_REQUIRE_RE):
            for match in pattern.finditer(content):
                module = match.group(1)
                if module not in seen:
                    seen.append(module)
        return seen

    def extract_functions(self, content: str) -> list[str]:
        names = []
        for match in _JS_FUNC_RE.finditer(content):
            name = match.group(1) or match.group(2)
            if name and name not in names:
                names.append(name)
        return names

    def extract_classes(self, content: str) -> list[str]:
        return list(dict.fromkeys(match.group(1) for match in _JS_CLASS_RE.finditer(content)))

    def extract_routes(self, content: str) -> list[dict]:
        return [
            {"method": match.group(1).upper(), "path": match.group(2), "line": content[: match.start()].count("\n") + 1}
            for match in _JS_ROUTE_RE.finditer(content)
        ]
