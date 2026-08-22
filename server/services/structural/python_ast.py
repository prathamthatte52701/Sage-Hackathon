import ast
from dataclasses import dataclass, field


@dataclass
class PythonCall:
    name: str
    line: int
    args: list[str] = field(default_factory=list)


@dataclass
class PythonFunction:
    name: str
    start_line: int
    end_line: int
    args: list[str]
    is_async: bool
    decorators: list[str] = field(default_factory=list)
    returns: list[int] = field(default_factory=list)
    calls: list[PythonCall] = field(default_factory=list)
    exception_handlers: list[int] = field(default_factory=list)
    assignments: list[str] = field(default_factory=list)
    awaits: list[int] = field(default_factory=list)
    routes: list[dict] = field(default_factory=list)


@dataclass
class PythonClass:
    name: str
    start_line: int
    end_line: int
    decorators: list[str] = field(default_factory=list)
    methods: list[PythonFunction] = field(default_factory=list)


@dataclass
class PythonModule:
    imports: list[str] = field(default_factory=list)
    from_imports: list[str] = field(default_factory=list)
    assignments: list[str] = field(default_factory=list)
    functions: list[PythonFunction] = field(default_factory=list)
    classes: list[PythonClass] = field(default_factory=list)
    parse_error: str | None = None
    tree: ast.Module | None = field(default=None, repr=False)


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _name(node.func)
    if isinstance(node, ast.Constant):
        return repr(node.value)
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    return [_name(decorator) for decorator in node.decorator_list if _name(decorator)]


def _route_from_decorator(decorator: ast.AST, handler: str, line: int) -> dict | None:
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return None
    method = decorator.func.attr.upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return None
    if not decorator.args or not isinstance(decorator.args[0], ast.Constant) or not isinstance(decorator.args[0].value, str):
        return None
    owner = _name(decorator.func.value)
    if owner not in {"app", "router", "api", "blueprint", "bp"} and not owner.endswith("router"):
        return None
    return {"method": method, "path": decorator.args[0].value, "line": line, "handler": handler}


def _call(node: ast.Call) -> PythonCall:
    args = [_name(arg) for arg in node.args]
    args.extend(f"{kw.arg}={_name(kw.value)}" for kw in node.keywords if kw.arg)
    return PythonCall(name=_name(node.func), line=getattr(node, "lineno", 0), args=[arg for arg in args if arg])


def _assignment_targets(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> list[str]:
    targets = []
    raw_targets = getattr(node, "targets", None) or [getattr(node, "target", None)]
    for target in raw_targets:
        if target is not None:
            rendered = _name(target)
            if rendered:
                targets.append(rendered)
    return targets


def _function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> PythonFunction:
    calls = [_call(child) for child in ast.walk(node) if isinstance(child, ast.Call)]
    routes = []
    for decorator in node.decorator_list:
        route = _route_from_decorator(decorator, node.name, node.lineno)
        if route:
            routes.append(route)
    assignments = []
    for child in ast.walk(node):
        if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            assignments.extend(_assignment_targets(child))
    return PythonFunction(
        name=node.name,
        start_line=node.lineno,
        end_line=getattr(node, "end_lineno", node.lineno),
        args=[arg.arg for arg in node.args.args],
        is_async=isinstance(node, ast.AsyncFunctionDef),
        decorators=_decorators(node),
        returns=[child.lineno for child in ast.walk(node) if isinstance(child, ast.Return)],
        calls=calls,
        exception_handlers=[child.lineno for child in ast.walk(node) if isinstance(child, ast.ExceptHandler)],
        assignments=assignments,
        awaits=[child.lineno for child in ast.walk(node) if isinstance(child, ast.Await)],
        routes=routes,
    )


def analyze_python_source(content: str) -> PythonModule:
    try:
        tree = ast.parse(content or "")
    except SyntaxError as exc:
        return PythonModule(parse_error=str(exc))

    module = PythonModule(tree=tree)
    parent_by_child = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module.imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                prefix = "." * node.level
                module.from_imports.append(f"{prefix}{node.module}" if node.module else prefix)

    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            module.assignments.extend(_assignment_targets(node))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module.functions.append(_function(node))
        elif isinstance(node, ast.ClassDef):
            methods = [
                _function(child)
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            module.classes.append(
                PythonClass(
                    name=node.name,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    decorators=_decorators(node),
                    methods=methods,
                )
            )
    module.functions.sort(key=lambda fn: (fn.start_line, fn.end_line, fn.name))
    module.classes.sort(key=lambda cls: (cls.start_line, cls.end_line, cls.name))
    return module


def line_range(content: str, start_line: int, end_line: int) -> str:
    lines = (content or "").splitlines()
    start = max(start_line, 1) - 1
    end = min(max(end_line, start_line), len(lines))
    return "\n".join(lines[start:end])


def enclosing_symbol_for_line(module: PythonModule, line: int) -> PythonFunction | PythonClass | None:
    candidates: list[PythonFunction | PythonClass] = []
    candidates.extend(fn for fn in module.functions if fn.start_line <= line <= fn.end_line)
    for cls in module.classes:
        if cls.start_line <= line <= cls.end_line:
            candidates.append(cls)
        candidates.extend(fn for fn in cls.methods if fn.start_line <= line <= fn.end_line)
    if not candidates:
        return None
    return min(candidates, key=lambda item: item.end_line - item.start_line)
