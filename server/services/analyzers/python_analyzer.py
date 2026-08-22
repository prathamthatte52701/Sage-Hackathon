"""Genuine ast-based extraction, relocated unchanged from the old
services/analyzer.py. Behavior is identical to before this refactor - only
the home address changed.
"""

import ast

from .base import LanguageAnalyzer


class PythonAnalyzer(LanguageAnalyzer):
    language = "python"

    def extract_imports(self, content: str) -> list[str]:
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

    def extract_functions(self, content: str) -> list[str]:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []
        return [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

    def extract_classes(self, content: str) -> list[str]:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []
        return [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]

    def extract_routes(self, content: str) -> list[dict]:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        routes = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute):
                    continue
                method = func.attr.upper()
                if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                    continue
                if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                    continue
                path = decorator.args[0].value
                if isinstance(path, str):
                    routes.append({"method": method, "path": path, "line": node.lineno, "handler": node.name})
        return routes

    def parse_error_safe(self, content: str) -> str | None:
        try:
            ast.parse(content)
        except SyntaxError as exc:
            return str(exc)
        return None
