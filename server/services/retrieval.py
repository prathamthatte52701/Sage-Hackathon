"""Phase 10B, Stage 1 retrieval: keyword matching against names already
extracted by the Phase 3 analyzer (file paths, function/class names, imports)
plus a content scan. No embeddings, no vector DB — per the constitution's own
escalation rule, only add that complexity if this genuinely proves insufficient.

Stage 2 (build_import_graph / get_related_files, added below) layers a
structural signal on top: files connected by import/dependency edges, in
both directions, so "what depends on X" and "what breaks if I change X"
questions are answered by real code relationships instead of vocabulary
overlap. Stage 1 is untouched — Stage 2 only expands its candidate set.
"""

import os
import re
from pathlib import PurePosixPath

from services.security_findings import authoritative_security_findings

_STOPWORDS = {
    "the", "is", "at", "which", "on", "a", "an", "and", "or", "of", "to", "in",
    "for", "this", "that", "does", "do", "how", "what", "where", "when", "why",
    "are", "was", "were", "be", "it", "its", "with", "from", "as", "has", "have",
}

_WORD_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{2,}")

CONTEXT_CHARS_PER_FILE = 1500

# "riskiest file" / "most vulnerable" questions aren't answerable by keyword
# overlap — that judgment lives in the findings list (severity per file), not
# file content. Route these to a severity ranking instead of guessing.
_RISK_WORDS = {
    "risk",
    "risky",
    "riskiest",
    "dangerous",
    "vulnerable",
    "vulnerability",
    "vulnerabilities",
    "insecure",
    "security",
    "secure",
    "production",
    "readiness",
    "worst",
    "unsafe",
}
_SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_DATABASE_WORDS = {"database", "databases", "db", "sqlite", "sql", "query", "queries"}
_DATABASE_FILE_STEMS = {"db", "database", "database_client", "repository", "repositories", "models"}

_SOURCE_EXT_RE = re.compile(r"\.(py|js|jsx|ts|tsx)$")
STRUCTURAL_SCORE_WEIGHT = 0.5  # a structurally-related file scores lower than a real keyword hit
MAX_TOTAL_FILES = 8  # keeps Stage 2 expansion bounded so LLM context stays focused


def build_import_graph(project: dict) -> dict[str, set[str]]:
    """Returns {file_path: {other_file_paths_it_imports}}. Resolves import
    module strings (already extracted by the Phase 3 analyzer into
    project["imports"]) to actual file paths within the project. Imports
    that resolve to external packages (not in the project) are dropped —
    only project-internal relationships matter for retrieval.

    Best-effort resolver, not a real module system: handles absolute dotted
    Python imports ("app.services.db" -> "app/services/db.py"), sibling-style
    Python imports ("from db import x" resolved relative to the importer's
    directory), and relative JS/TS imports ("./db", "../services/db",
    optionally with an implied /index).
    """
    all_paths = {f.get("path") for f in project.get("files", []) if f.get("path")}

    path_by_stripped: dict[str, str] = {}
    path_by_dotted: dict[str, str] = {}
    for path in all_paths:
        stripped = _SOURCE_EXT_RE.sub("", path)
        path_by_stripped[stripped] = path
        path_by_dotted[stripped.replace("/", ".")] = path

    def resolve(importer_path: str, module: str) -> str | None:
        if not module:
            return None

        importer_dir = str(PurePosixPath(importer_path).parent)
        if importer_dir == ".":
            importer_dir = ""

        candidates = []
        if module.startswith("."):
            # relative JS/TS import: ./x, ../x/y
            joined = os.path.normpath(f"{importer_dir}/{module}").replace("\\", "/")
            candidates.append(joined)
            candidates.append(f"{joined}/index")
        else:
            # absolute-from-project-root dotted Python import
            candidates.append(module.replace(".", "/"))
            # sibling-relative Python import (from db import x, meaning a
            # module next to the importer, not project-root-absolute)
            if importer_dir:
                candidates.append(f"{importer_dir}/{module.replace('.', '/')}")

        for candidate in candidates:
            candidate = candidate.lstrip("/")
            if candidate in path_by_stripped:
                return path_by_stripped[candidate]
            dotted = candidate.replace("/", ".")
            if dotted in path_by_dotted:
                return path_by_dotted[dotted]
        return None

    graph: dict[str, set[str]] = {path: set() for path in all_paths}
    for entry in project.get("imports", []):
        importer = entry.get("file")
        if importer not in graph:
            continue
        target = resolve(importer, entry.get("module", ""))
        if target and target != importer:
            graph[importer].add(target)

    return graph


def get_related_files(file_path: str, import_graph: dict, depth: int = 1) -> set[str]:
    """Files this file imports, AND files that import this file (both
    directions — a caller needs to know its dependents too, e.g. "what
    breaks if I change this model" needs reverse lookups)."""
    related = set(import_graph.get(file_path, set()))
    related |= {other for other, targets in import_graph.items() if file_path in targets}
    related.discard(file_path)

    frontier = related
    for _ in range(depth - 1):
        next_frontier = set()
        for path in frontier:
            next_frontier |= get_related_files(path, import_graph, depth=1)
        new = next_frontier - related - {file_path}
        if not new:
            break
        related |= new
        frontier = new

    return related


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text) if t.lower() not in _STOPWORDS}


def _rank_by_finding_severity(project: dict, top_k: int) -> list[dict]:
    severity_by_file: dict[str, int] = {}
    for f in authoritative_security_findings(project):
        path = f.get("file")
        if path:
            severity_by_file[path] = severity_by_file.get(path, 0) + _SEVERITY_WEIGHT.get(f.get("severity"), 0)

    files_by_path = {f.get("path"): f for f in project.get("files", [])}
    ranked = sorted(severity_by_file.items(), key=lambda pair: pair[1], reverse=True)

    results = []
    for path, weight in ranked[:top_k]:
        file_entry = files_by_path.get(path)
        if not file_entry:
            continue
        content = file_entry.get("content") or ""
        results.append(
            {
                "path": path,
                "language": file_entry.get("language"),
                "score": weight,
                "snippet": content[:CONTEXT_CHARS_PER_FILE],
            }
        )
    return results


def retrieve_relevant_files(project: dict, question: str, top_k: int = 5) -> list[dict]:
    q_tokens = _tokens(question)
    question_lower = question.lower()
    # _tokens() drops anything under 3 chars, so a short filename like
    # "db.py" never becomes a token and q_tokens can end up empty even
    # though the question names an exact file. Check for a literal path
    # mention before the early-exit so "What does db.py do?" doesn't
    # short-circuit to zero results.
    has_literal_path_mention = any(
        f.get("path") and f["path"].lower() in question_lower for f in project.get("files", [])
    )
    if not q_tokens and not has_literal_path_mention:
        return []

    if q_tokens & _RISK_WORDS:
        ranked = _rank_by_finding_severity(project, top_k)
        if ranked:
            return ranked
        # no findings to rank by — fall through to normal keyword retrieval

    functions_by_file: dict[str, list[str]] = {}
    for f in project.get("functions", []):
        functions_by_file.setdefault(f.get("file"), []).append(f.get("name", ""))
    classes_by_file: dict[str, list[str]] = {}
    for c in project.get("classes", []):
        classes_by_file.setdefault(c.get("file"), []).append(c.get("name", ""))
    imports_by_file: dict[str, list[str]] = {}
    for i in project.get("imports", []):
        imports_by_file.setdefault(i.get("file"), []).append(i.get("module", ""))

    files_by_path = {f.get("path"): f for f in project.get("files", [])}

    scored = []
    for file_entry in project.get("files", []):
        path = file_entry.get("path", "")
        content = file_entry.get("content") or ""

        path_tokens = _tokens(PurePosixPath(path).stem.replace("_", " ").replace("-", " "))
        name_tokens = {n.lower() for n in functions_by_file.get(path, [])} | {
            n.lower() for n in classes_by_file.get(path, [])
        }
        import_tokens = set()
        for m in imports_by_file.get(path, []):
            import_tokens |= _tokens(m)

        score = 0
        score += 3 * len(q_tokens & path_tokens)
        score += 2 * len(q_tokens & name_tokens)
        score += 2 * len(q_tokens & import_tokens)
        if content:
            content_lower = content.lower()
            score += sum(1 for t in q_tokens if t in content_lower)

            # "database" intent often points at files named db.py or SQL code
            # that does not literally contain the word "database". Without this
            # boost, DATABASE_PASSWORD in config.py can outrank the actual DB
            # access layer during demo chat.
            path_stem = PurePosixPath(path).stem.lower()
            if q_tokens & _DATABASE_WORDS:
                if path_stem in _DATABASE_FILE_STEMS:
                    score = max(score, 8)
                if any(marker in content_lower for marker in ("sqlite3", "select ", "insert ", "update ", "delete ")):
                    score = max(score, 7)

        # Stage 1's path score only tokenizes the filename stem, so a
        # question naming a full path ("app/services/db.py") can score 0
        # against the very file it's asking about — a directory component
        # never gets tokenized. A literal path mention is a strong enough
        # signal to treat as a top hit regardless, so Stage 2 has a real
        # seed to expand from.
        if path and path.lower() in question_lower:
            score = max(score, 10)

        if score > 0:
            scored.append((score, file_entry))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    stage1 = scored[:top_k]

    results = []
    seen_paths = set()
    for score, file_entry in stage1:
        path = file_entry.get("path")
        seen_paths.add(path)
        content = file_entry.get("content") or ""
        results.append(
            {
                "path": path,
                "language": file_entry.get("language"),
                "score": score,
                "snippet": content[:CONTEXT_CHARS_PER_FILE],
            }
        )

    # Stage 2: expand with structurally related files (import graph), lower
    # weight than a real keyword hit, bounded so context stays focused
    # rather than bloated.
    if stage1 and len(results) < MAX_TOTAL_FILES:
        import_graph = build_import_graph(project)
        for score, file_entry in stage1:
            if len(results) >= MAX_TOTAL_FILES:
                break
            related = get_related_files(file_entry.get("path"), import_graph, depth=1)
            for rel_path in sorted(related):
                if len(results) >= MAX_TOTAL_FILES:
                    break
                if rel_path in seen_paths:
                    continue
                rel_entry = files_by_path.get(rel_path)
                if not rel_entry:
                    continue
                seen_paths.add(rel_path)
                content = rel_entry.get("content") or ""
                results.append(
                    {
                        "path": rel_path,
                        "language": rel_entry.get("language"),
                        "score": round(score * STRUCTURAL_SCORE_WEIGHT, 2),
                        "snippet": content[:CONTEXT_CHARS_PER_FILE],
                    }
                )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


async def retrieve_semantic_project_context(project: dict, question: str, top_k: int = 2, owner_user_id: str = "") -> list[dict]:
    """Stage 3 (optional, additive): cross-project semantic context via the
    `projects.embedding` vector search index. Project embeddings in this repo
    are one vector per project (built from concatenated file text — see
    generate_embeddings.py), not one per file. That means vector search here
    can only ever surface *other* projects that are semantically similar to
    the question — it cannot do file-level semantic retrieval within the
    current project. Stage 1/2 above (retrieve_relevant_files) already own
    that job precisely via keyword/import matching and remain the sole
    source of PROJECT EVIDENCE for the current project.

    Scoped to the authenticated owner (and session_id when present), so a
    client-controlled session ID can never become the authorization boundary.

    Fails silently (returns []) on any error — no MONGO_URL, embedding model
    unavailable, Atlas index down, bad ObjectId — so this optional enrichment
    can never break the chat endpoint.
    """
    try:
        import asyncio

        from db.mongo import get_db
        from services.embeddings import generate_embedding

        db = get_db()
        if db is None:
            return []

        current_id = project.get("_id")
        session_id = project.get("session_id")
        owner = owner_user_id or project.get("owner_user_id")

        # model.encode() is synchronous/CPU-bound; running it directly on the
        # event loop can starve Starlette's BaseHTTPMiddleware task group
        # (rate_limit_middleware), so offload it like knowledge/embeddings.py does.
        vector = await asyncio.to_thread(generate_embedding, question)
        # Atlas index has no filter fields defined (only the vector path), so
        # session/self scoping can't happen inside $vectorSearch itself —
        # over-fetch and filter in Python instead.
        overfetch = max(top_k * 5, 10)
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": vector,
                    "numCandidates": max(50, overfetch * 10),
                    "limit": overfetch,
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "session_id": 1,
                    "owner_user_id": 1,
                    "name": "$project.name",
                    "projectType": "$project.projectType",
                    "languages": "$project.languages",
                    "overall_score": "$compliance_score.overall_score",
                    "similarity": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        candidates = await db.projects.aggregate(pipeline).to_list(length=overfetch)
    except Exception:
        return []

    results = []
    for c in candidates:
        if str(c.get("_id")) == str(current_id):
            continue
        if owner and c.get("owner_user_id") != owner:
            continue
        if session_id and c.get("session_id") != session_id:
            continue
        c["_id"] = str(c["_id"])
        c.pop("session_id", None)
        c.pop("owner_user_id", None)
        results.append(c)
        if len(results) >= top_k:
            break

    return results
