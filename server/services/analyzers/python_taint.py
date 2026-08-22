"""Small, deterministic Python source-to-sink taint analysis.

This is intentionally a bounded intra-file analysis.  It tracks request
values through assignments, simple expressions, containers, and a small set
of local function returns.  It never imports or executes analyzed code.
"""

import ast
from dataclasses import dataclass, field


_REQUEST_ATTRS = {"args", "form", "json", "query_params", "query", "params", "body"}
_SQL_SINKS = {"execute", "executemany", "executescript"}
_HTTP_MODULES = {"requests", "httpx"}
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "request"}
_COMMAND_MODULES = {"os", "subprocess"}
_COMMAND_METHODS = {"system", "popen", "run", "popen", "call", "check_call", "check_output", "Popen"}
_SANITIZER_PREFIXES = ("validate_", "sanitize_", "escape_", "safe_", "is_valid_", "is_allowed_")


@dataclass
class _Taint:
    source_line: int
    source_expression: str
    steps: list[str] = field(default_factory=list)

    def through(self, expression: str) -> "_Taint":
        return _Taint(self.source_line, self.source_expression, [*self.steps, expression])


@dataclass
class _FunctionSummary:
    returns_from: set[str] = field(default_factory=set)


def _name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _name(node.value)
        return f"{owner}.{node.attr}" if owner else node.attr
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _source_segment(source: str, node: ast.AST) -> str:
    return (ast.get_source_segment(source, node) or _name(node) or "")[:240]


def _call_name(node: ast.Call) -> str:
    return _name(node.func)


def _is_sanitizer(name: str) -> bool:
    short = name.rsplit(".", 1)[-1]
    return short.startswith(_SANITIZER_PREFIXES)


def _targets(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> list[str]:
    raw = getattr(node, "targets", None) or [getattr(node, "target", None)]
    return [target.id for target in raw if isinstance(target, ast.Name)]


def _request_source(node: ast.AST, request_names: set[str], source: str) -> _Taint | None:
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
        if isinstance(node.value.value, ast.Name) and node.value.value.id in request_names and node.value.attr in _REQUEST_ATTRS:
            expression = _source_segment(source, node)
            return _Taint(node.lineno, expression, [expression])
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        owner = node.func.value
        if isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name):
            if owner.value.id in request_names and owner.attr in _REQUEST_ATTRS and node.func.attr == "get":
                expression = _source_segment(source, node)
                return _Taint(node.lineno, expression, [expression])
    return None


def _merge(values: list[_Taint | None], expression: str) -> _Taint | None:
    for value in values:
        if value is not None:
            return value.through(expression)
    return None


def _function_summaries(tree: ast.Module) -> dict[str, _FunctionSummary]:
    summaries: dict[str, _FunctionSummary] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = {arg.arg for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]}
        returned: set[str] = set()
        for child in ast.walk(node):
            if not isinstance(child, ast.Return) or child.value is None:
                continue
            for name in params:
                if any(isinstance(part, ast.Name) and part.id == name for part in ast.walk(child.value)):
                    if not (_is_sanitizer(_call_name(child.value)) if isinstance(child.value, ast.Call) else False):
                        returned.add(name)
        summaries[node.name] = _FunctionSummary(returned)
    return summaries


class _TaintWalker:
    def __init__(self, source: str, tree: ast.Module, path: str):
        self.source = source
        self.tree = tree
        self.path = path
        self.summaries = _function_summaries(tree)
        self.findings: list[dict] = []
        self._analyzed_local_calls: set[int] = set()

    def _local_function(self, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        short = name.rsplit(".", 1)[-1]
        return next(
            (item for item in ast.walk(self.tree) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == short),
            None,
        )

    def _identity_sanitizer(self, name: str) -> bool:
        function = self._local_function(name)
        if function is None:
            return False
        params = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
        parameter_names = {param.arg for param in params}
        return any(
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Name)
            and node.value.id in parameter_names
            for node in ast.walk(function)
        )

    def _eval(self, node: ast.AST | None, state: dict[str, _Taint], request_names: set[str]) -> _Taint | None:
        if node is None:
            return None
        direct = _request_source(node, request_names, self.source)
        if direct:
            return direct
        if isinstance(node, ast.Name):
            value = state.get(node.id)
            return value.through(_source_segment(self.source, node)) if value else None
        if isinstance(node, ast.JoinedStr):
            return _merge([self._eval(value.value, state, request_names) for value in node.values if isinstance(value, ast.FormattedValue)], _source_segment(self.source, node))
        if isinstance(node, ast.BinOp):
            return _merge([self._eval(node.left, state, request_names), self._eval(node.right, state, request_names)], _source_segment(self.source, node))
        if isinstance(node, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
            children = list(ast.iter_child_nodes(node))
            return _merge([self._eval(child, state, request_names) for child in children], _source_segment(self.source, node))
        if isinstance(node, ast.Call):
            name = _call_name(node)
            args = [self._eval(arg, state, request_names) for arg in node.args]
            if _is_sanitizer(name) and not self._identity_sanitizer(name):
                return None
            summary = self.summaries.get(name.rsplit(".", 1)[-1])
            if summary:
                fn = self._local_function(name)
                if fn:
                    params = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
                    local_state = {
                        param.arg: args[index]
                        for index, param in enumerate(params)
                        if index < len(args) and args[index] is not None
                    }
                    call_id = id(node)
                    if call_id not in self._analyzed_local_calls:
                        self._analyzed_local_calls.add(call_id)
                        self._block(fn.body, local_state, {param.arg for param in params if param.arg in {"request", "req"}})
                    return _merge([args[index] for index, param in enumerate(params) if param.arg in summary.returns_from and index < len(args)], _source_segment(self.source, node))
            return _merge(args, _source_segment(self.source, node))
        for child in ast.iter_child_nodes(node):
            value = self._eval(child, state, request_names)
            if value:
                return value.through(_source_segment(self.source, node))
        return None

    def _add_finding(self, rule: str, severity: str, message: str, suggestion: str, sink: ast.Call, taint: _Taint) -> None:
        evidence = _source_segment(self.source, sink)
        self.findings.append({
            "file": self.path,
            "line": sink.lineno,
            "rule": rule,
            "severity": severity,
            "category": "security",
            "message": message,
            "evidence": evidence,
            "source_line": taint.source_line,
            "source_expression": taint.source_expression,
            "sink_expression": evidence,
            "sink_line": sink.lineno,
            "taint_path": [taint.source_expression, *taint.steps, evidence],
            "confidence": "high",
            "evidence_type": "ast_source_sink",
            "fix_suggestion": suggestion,
            "source": "deterministic",
        })

    def _sink(self, node: ast.Call, state: dict[str, _Taint], request_names: set[str]) -> None:
        name = _call_name(node)
        parts = name.split(".")
        if self._local_function(name) is not None:
            self._eval(node, state, request_names)
        taint = self._eval(node.args[0], state, request_names) if node.args else None
        if taint and parts[-1] in _SQL_SINKS and len(parts) >= 2:
            self._add_finding("sql_injection", "critical", "Request-derived input reaches SQL execution.", "Use parameterized SQL queries and keep user input in bound parameters.", node, taint)
        if taint and ((parts[0] == "os" and parts[-1] in {"system", "popen"}) or (parts[0] == "subprocess" and parts[-1] in _COMMAND_METHODS)):
            shell = any(keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True for keyword in node.keywords)
            if parts[0] == "os" or shell:
                self._add_finding("command_injection", "critical", "Request-derived input reaches command execution.", "Avoid shell execution and use a fixed argument list with strict validation.", node, taint)
        url_taint = taint
        if len(parts) == 2 and parts[0] in _HTTP_MODULES and parts[1] == "request" and len(node.args) >= 2:
            url_taint = self._eval(node.args[1], state, request_names)
        if url_taint and len(parts) == 2 and parts[0] in _HTTP_MODULES and parts[1] in _HTTP_METHODS:
            self._add_finding("ssrf", "high", "Request-derived URL reaches an outbound HTTP request.", "Allowlist destinations and validate the URL before making the request.", node, url_taint)
        if taint and name == "urllib.request.urlopen":
            self._add_finding("ssrf", "high", "Request-derived URL reaches an outbound HTTP request.", "Allowlist destinations and validate the URL before making the request.", node, taint)
        if taint and (name in {"mark_safe", "Markup"} or parts[-1] in {"mark_safe", "Markup"}):
            self._add_finding("xss_unsafe_html_sink", "high", "Request-derived content reaches a trusted HTML sink.", "Escape or sanitize HTML before marking it safe.", node, taint)

    def _block(self, statements: list[ast.stmt], state: dict[str, _Taint], request_names: set[str]) -> None:
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(statement, ast.If):
                guard_names = self._validator_guard_names(statement.test, state, request_names)
                before = dict(state)
                true_state = dict(state)
                false_state = dict(state)
                self._block(statement.body, true_state, request_names)
                self._block(statement.orelse, false_state, request_names)
                if guard_names and isinstance(statement.test, ast.UnaryOp) and isinstance(statement.test.op, ast.Not):
                    for name in guard_names:
                        false_state.pop(name, None)
                    state.clear()
                    state.update(false_state)
                    continue
                state.clear()
                for name in set(true_state) | set(false_state):
                    value = true_state.get(name) or false_state.get(name)
                    if value:
                        state[name] = value
                for name in set(before) - set(true_state) - set(false_state):
                    state.pop(name, None)
                continue
            if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                if isinstance(statement, (ast.For, ast.AsyncFor)):
                    iter_taint = self._eval(statement.iter, state, request_names)
                    if iter_taint and isinstance(statement.target, ast.Name):
                        state[statement.target.id] = iter_taint.through(statement.target.id)
                self._block(statement.body, state, request_names)
                self._block(statement.orelse, state, request_names)
                continue
            if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                value = statement.value if hasattr(statement, "value") else None
                taint = self._eval(value, state, request_names)
                for target in _targets(statement):
                    if isinstance(value, ast.Name) and value.id in {"request", "req"}:
                        request_names.add(target)
                    if taint:
                        state[target] = taint.through(target)
                    else:
                        state.pop(target, None)
            for node in ast.walk(statement):
                if isinstance(node, ast.Call):
                    self._sink(node, state, request_names)

    def _validator_guard_names(self, test: ast.AST, state: dict[str, _Taint], request_names: set[str]) -> set[str]:
        call = test.operand if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) else test
        if isinstance(call, ast.Call) and _is_sanitizer(_call_name(call)):
            return {arg.id for arg in call.args if isinstance(arg, ast.Name) and arg.id in state}
        return set()

    def run(self) -> list[dict]:
        # Module-level statements and every function get an independent state,
        # preventing same-name variables in separate scopes from bleeding together.
        self._block(self.tree.body, {}, {"request", "req"})
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                request_names = {arg.arg for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs] if arg.arg in {"request", "req"}}
                self._block(node.body, {}, request_names)
        return self.findings


def analyze_python_taint(path: str, content: str, tree: ast.Module | None = None) -> list[dict]:
    """Return evidence-backed source-to-sink findings, never raising on bad Python."""
    try:
        parsed = tree or ast.parse(content or "")
        return _TaintWalker(content or "", parsed, path).run()
    except (SyntaxError, ValueError, TypeError):
        return []
