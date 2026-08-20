from services.retrieval import build_import_graph, get_related_files


MAX_CONTEXT_CHARS = 6000
SNIPPET_RADIUS = 8


def extract_snippet(content: str, line: int, radius: int = SNIPPET_RADIUS) -> str:
    lines = content.splitlines()
    if not lines:
        return ""
    if line <= 0:
        return "\n".join(lines[: min(len(lines), radius * 2)])
    start = max(0, line - 1 - radius)
    end = min(len(lines), line - 1 + radius + 1)
    return "\n".join(lines[start:end])


def build_finding_context(project: dict, finding: dict) -> dict:
    files_by_path = {f.get("path"): f for f in project.get("files", [])}
    origin_path = finding.get("file", "")
    origin = files_by_path.get(origin_path)
    origin_content = (origin or {}).get("content") or ""
    origin_snippet = extract_snippet(origin_content, int(finding.get("line") or 0))

    graph = build_import_graph(project)
    related_paths = sorted(get_related_files(origin_path, graph, depth=1))

    related = []
    used = len(origin_snippet)
    for path in related_paths:
        entry = files_by_path.get(path)
        content = (entry or {}).get("content") or ""
        if not content:
            continue
        budget = max(0, MAX_CONTEXT_CHARS - used)
        if budget <= 0:
            break
        snippet = content[: min(1200, budget)]
        used += len(snippet)
        related.append({"path": path, "language": entry.get("language"), "snippet": snippet})

    return {
        "origin_file": origin_path,
        "language": (origin or {}).get("language") or "unknown",
        "snippet": origin_snippet or finding.get("evidence", ""),
        "related_files": related,
        "import_graph": {origin_path: sorted(graph.get(origin_path, set()))} if origin_path else {},
    }
