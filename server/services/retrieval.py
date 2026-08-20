"""Phase 10B, Stage 1 retrieval: keyword matching against names already
extracted by the Phase 3 analyzer (file paths, function/class names, imports)
plus a content scan. No embeddings, no vector DB — per the constitution's own
escalation rule, only add that complexity if this genuinely proves insufficient.
"""

import re
from pathlib import PurePosixPath

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
_RISK_WORDS = {"risk", "risky", "riskiest", "dangerous", "vulnerable", "insecure", "worst", "unsafe"}
_SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text) if t.lower() not in _STOPWORDS}


def _rank_by_finding_severity(project: dict, top_k: int) -> list[dict]:
    severity_by_file: dict[str, int] = {}
    for f in project.get("findings", []):
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
    if not q_tokens:
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

        if score > 0:
            scored.append((score, file_entry))

    scored.sort(key=lambda pair: pair[0], reverse=True)

    results = []
    for score, file_entry in scored[:top_k]:
        content = file_entry.get("content") or ""
        results.append(
            {
                "path": file_entry.get("path"),
                "language": file_entry.get("language"),
                "score": score,
                "snippet": content[:CONTEXT_CHARS_PER_FILE],
            }
        )
    return results
