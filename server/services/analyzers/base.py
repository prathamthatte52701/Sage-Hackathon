"""Common interface every per-language analyzer implements.

analyzer.py loops over files and calls into whichever analyzer the registry
(__init__.py) resolves for that file's language - it never branches on
language itself. Each analyzer owns its own parsing strategy (real AST for
Python, regex for JS/TS today) behind this one shape.
"""

from abc import ABC, abstractmethod


class LanguageAnalyzer(ABC):
    language: str

    @abstractmethod
    def extract_imports(self, content: str) -> list[str]: ...

    @abstractmethod
    def extract_functions(self, content: str) -> list[str]: ...

    @abstractmethod
    def extract_classes(self, content: str) -> list[str]: ...

    def extract_routes(self, content: str) -> list[dict]:
        return []

    def parse_error_safe(self, content: str) -> str | None:
        """Return an error message if the file couldn't be parsed, else None.
        Never raise - the caller must be able to skip this file and continue.
        """
        return None
