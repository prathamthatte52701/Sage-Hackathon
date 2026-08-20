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
        return []

    def extract_classes(self, content: str) -> list[str]:
        return []
