from .base import LanguageAnalyzer
from .javascript_analyzer import JavaScriptAnalyzer
from .python_analyzer import PythonAnalyzer

_ANALYZERS: dict[str, LanguageAnalyzer] = {
    "python": PythonAnalyzer(),
    "javascript": JavaScriptAnalyzer(),
    "typescript": JavaScriptAnalyzer(),  # reuse JS analyzer for TS for now
}


def get_analyzer(language: str) -> LanguageAnalyzer | None:
    return _ANALYZERS.get(language)
