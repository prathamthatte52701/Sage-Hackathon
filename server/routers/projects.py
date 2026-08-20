import copy
import os
import re
import zipfile
from io import BytesIO
from pathlib import PurePosixPath

import httpx
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from db.mongo import get_project, save_project, update_project
from models.schemas import ChatRequest, FindingReasonRequest, FindingReasoning, FindingTransform, GithubImportRequest
from services.analyzer import SOURCE_LANGUAGES, analyze_project
from services.reasoning_engine import answer_project_question, confirm_and_explain_finding, generate_fix
from services.retrieval import retrieve_relevant_files
from services.scoring import FINDING_CATEGORY_MAP, RULE_TO_STANDARD, compute_score
from services.standards import get_standard_by_id, get_standards_for

router = APIRouter()

MAX_ZIP_SIZE = 300 * 1024 * 1024  # 300MB
MAX_FILE_COUNT = 2000
MAX_CONTENT_SIZE = 100_000  # chars

IGNORE_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", "coverage", ".cache"}

EXTENSION_LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
}

_ERROR_RESPONSE = {"error": "Could not process the uploaded project, please try again"}


def _guess_language(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return EXTENSION_LANGUAGE_MAP.get(ext, "other")


def _is_unsafe_path(name: str) -> bool:
    """Reject path traversal, absolute paths, and Windows drive-letter paths."""
    normalized = name.replace("\\", "/")
    if ".." in PurePosixPath(normalized).parts:
        return True
    if normalized.startswith("/"):
        return True
    if len(normalized) >= 2 and normalized[1] == ":":  # e.g. C:\ or C:/
        return True
    # belt-and-suspenders: resolved path must stay under the extraction root
    resolved = os.path.normpath(os.path.join("ROOT", normalized))
    if resolved == ".." or resolved.startswith(".." + os.sep) or not resolved.startswith("ROOT"):
        return True
    return False


def _is_ignored(name: str) -> bool:
    parts = PurePosixPath(name.replace("\\", "/")).parts
    return any(part in IGNORE_DIRS for part in parts)


def _derive_project_name(filename: str | None) -> str:
    if not filename:
        return "unnamed-project"
    base = os.path.basename(filename)
    if base.lower().endswith(".zip"):
        base = base[:-4]
    return base or "unnamed-project"


def _strip_common_top_level(names: list[str]) -> str:
    """GitHub's zipball wraps everything in a single '{repo}-{sha}/' dir. Detect
    and return that prefix (empty string if there isn't a single common one) so
    callers can present normal-looking paths instead of a repo-specific wrapper.
    """
    tops = {name.split("/", 1)[0] for name in names if "/" in name}
    if len(tops) == 1:
        return next(iter(tops)) + "/"
    return ""


def _project_from_zip_bytes(raw_bytes: bytes, project_name: str, strip_top_level: bool = False):
    """Shared by ZIP upload and GitHub import: one normalized project
    representation, one analysis pipeline downstream — never two.

    Returns (project_representation, upload_warnings, error_response). Exactly
    one of (project_representation, error_response) is None.
    """
    if len(raw_bytes) > MAX_ZIP_SIZE:
        return None, None, {"error": "ZIP file exceeds the 300MB limit"}

    buffer = BytesIO(raw_bytes)
    if not zipfile.is_zipfile(buffer):
        return None, None, {"error": "Uploaded file is not a valid ZIP archive"}

    with zipfile.ZipFile(buffer) as zf:
        names = zf.namelist()

        if len(names) > MAX_FILE_COUNT:
            return None, None, {"error": f"ZIP contains too many files (max {MAX_FILE_COUNT})"}

        if any(_is_unsafe_path(name) for name in names):
            return None, None, {"error": "ZIP contains unsafe file paths"}

        prefix = _strip_common_top_level(names) if strip_top_level else ""

        files_index = []
        ignored_counts: dict[str, int] = {}

        for name in names:
            if name.endswith("/"):
                continue  # directory entry

            display_name = name[len(prefix):] if prefix and name.startswith(prefix) else name
            if not display_name:
                continue

            if _is_ignored(display_name):
                top_ignored = next(
                    part for part in PurePosixPath(display_name.replace("\\", "/")).parts if part in IGNORE_DIRS
                )
                ignored_counts[top_ignored] = ignored_counts.get(top_ignored, 0) + 1
                continue

            info = zf.getinfo(name)
            language = _guess_language(display_name)

            content = None
            if language in SOURCE_LANGUAGES:
                text = zf.read(name).decode("utf-8", errors="replace")
                if len(text) < MAX_CONTENT_SIZE:
                    content = text

            files_index.append(
                {"path": display_name, "language": language, "size": info.file_size, "content": content}
            )

    warnings = [f"skipped {count} file(s) under {dirname}/" for dirname, count in ignored_counts.items()]

    languages = sorted({f["language"] for f in files_index if f["language"] != "other"})

    frameworks = set()
    for f in files_index:
        p = f["path"]
        if p.endswith("package.json"):
            frameworks.add("node")
        if p.endswith("requirements.txt") or p.endswith("pyproject.toml"):
            frameworks.add("python")
        if p.endswith("pom.xml") or p.endswith("build.gradle"):
            frameworks.add("java")

    if not files_index:
        project_type = "unknown"
    elif len(languages) == 1:
        project_type = languages[0]
    else:
        project_type = "multi-language"

    directories = set()
    for f in files_index:
        parent = PurePosixPath(f["path"]).parent
        if str(parent) != ".":
            parts = parent.parts
            for i in range(1, len(parts) + 1):
                directories.add("/".join(parts[:i]))

    project_representation = {
        "project": {
            "name": project_name,
            "languages": languages,
            "frameworks": sorted(frameworks),
            "projectType": project_type,
        },
        "files": files_index,
        "directories": sorted(directories),
        "dependencies": [],
        "imports": [],
        "functions": [],
        "classes": [],
        "apiEndpoints": [],
        "tests": [],
        "configs": [],
        "deploymentFiles": [],
        "findings": [],
        "warnings": [],
    }

    return project_representation, warnings, None


@router.post("/projects/upload")
async def upload_project(file: UploadFile = File(...), session_id: str = Form(...)):
    try:
        raw_bytes = await file.read()

        project_representation, warnings, error = _project_from_zip_bytes(
            raw_bytes, _derive_project_name(file.filename)
        )
        if error is not None:
            return JSONResponse(status_code=400, content=error)

        project_id = await save_project(project_representation, session_id)

        return {"project_id": project_id, "project": project_representation, "warnings": warnings}
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_ERROR_RESPONSE)


_GITHUB_URL_RE = re.compile(
    r"^(?:https?://github\.com/)?([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)/"
    r"([A-Za-z0-9._-]+?)(?:\.git)?/?$"
)

_GITHUB_ERROR_RESPONSE = {"error": "Could not import this GitHub repository, please try again"}


def _parse_github_repo(repo_url: str):
    """Accepts 'owner/repo' or a github.com URL; rejects anything else (no
    private-repo/OAuth complexity in scope, so only this narrow shape matters).
    """
    match = _GITHUB_URL_RE.match(repo_url.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


@router.post("/projects/github")
async def import_from_github(payload: GithubImportRequest):
    try:
        parsed = _parse_github_repo(payload.repo_url)
        if parsed is None:
            return JSONResponse(
                status_code=400, content={"error": "Enter a GitHub repo as 'owner/repo' or a github.com URL"}
            )
        owner, repo = parsed

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}/zipball")
        except httpx.RequestError:
            return JSONResponse(status_code=400, content={"error": "Could not reach GitHub, please try again"})

        if resp.status_code == 404:
            return JSONResponse(
                status_code=400, content={"error": "Repository not found — check it's public and the name is correct"}
            )
        if resp.status_code == 403:
            return JSONResponse(
                status_code=400, content={"error": "GitHub rate limit hit — try again in a minute, or use ZIP upload"}
            )
        if resp.status_code != 200:
            return JSONResponse(status_code=400, content={"error": "GitHub declined this request, please try again"})

        # Same normalized representation as ZIP upload — no separate GitHub
        # analysis path. strip_top_level peels off zipball's '{repo}-{sha}/' wrapper.
        project_representation, warnings, error = _project_from_zip_bytes(
            resp.content, repo, strip_top_level=True
        )
        if error is not None:
            return JSONResponse(status_code=400, content=error)

        project_id = await save_project(project_representation, payload.session_id)

        return {"project_id": project_id, "project": project_representation, "warnings": warnings}
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_GITHUB_ERROR_RESPONSE)


@router.get("/projects/{project_id}")
async def get_project_by_id(project_id: str):
    try:
        project = await get_project(project_id)
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        return project
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_ERROR_RESPONSE)


_ANALYZE_ERROR_RESPONSE = {"error": "Could not analyze this project, please try again"}


@router.post("/projects/{project_id}/analyze")
async def analyze_project_by_id(project_id: str):
    try:
        project = await get_project(project_id)
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        analyzed = analyze_project(project)

        updates = {
            key: analyzed.get(key, [])
            for key in ("imports", "functions", "classes", "tests", "configs", "deploymentFiles", "findings", "warnings")
        }
        await update_project(project_id, updates)

        return analyzed
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_ANALYZE_ERROR_RESPONSE)


_SCORE_ERROR_RESPONSE = {"error": "Could not score this project, please try again"}


@router.post("/projects/{project_id}/score")
async def score_project_by_id(project_id: str):
    try:
        project = await get_project(project_id)
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        score = compute_score(project)
        await update_project(project_id, {"compliance_score": score})

        return score
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_SCORE_ERROR_RESPONSE)


def _extract_code_snippet(files: list, file_path: str, line: int) -> str:
    """Lines [line-5, line+5] (1-indexed, clamped) from the matching file's content.

    Falls back to the finding's own evidence string if the file isn't found or
    has no stored content — never send empty context to the LLM, never crash.
    """
    entry = next((f for f in files if f.get("path") == file_path), None)
    content = entry.get("content") if entry else None
    if not content:
        return ""

    lines = content.splitlines()
    if not lines:
        return ""

    start = max(0, (line - 1) - 5)
    end = min(len(lines), (line - 1) + 5 + 1)
    return "\n".join(lines[start:end])


_REASON_ERROR_RESPONSE = {"error": "Could not reason about this finding, please try again"}


@router.post("/projects/{project_id}/findings/reason", response_model=FindingReasoning)
async def reason_about_finding(project_id: str, payload: FindingReasonRequest):
    try:
        project = await get_project(project_id)
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        findings = project.get("findings", [])
        if payload.finding_index < 0 or payload.finding_index >= len(findings):
            return JSONResponse(status_code=400, content={"error": "Invalid finding index"})

        finding = findings[payload.finding_index]

        code_snippet = _extract_code_snippet(project.get("files", []), finding.get("file", ""), finding.get("line", 0))
        if not code_snippet:
            code_snippet = finding.get("evidence", "")

        file_entry = next((f for f in project.get("files", []) if f.get("path") == finding.get("file")), None)
        language = (file_entry or {}).get("language") or "unknown"

        # Prefer the rule's directly-mapped standard; the citation is attached
        # server-side (not trusted from the LLM output) so it's always accurate.
        standard_id = RULE_TO_STANDARD.get(finding.get("rule"))
        matched_standards = [get_standard_by_id(standard_id)] if standard_id else []
        if not matched_standards:
            weight_category = FINDING_CATEGORY_MAP.get(finding.get("category"))
            if weight_category:
                matched_standards = get_standards_for(weight_category, language)[:2]

        result = await confirm_and_explain_finding(finding, code_snippet, language, matched_standards)

        try:
            findings[payload.finding_index]["reasoning"] = result.model_dump()
            await update_project(project_id, {"findings": findings})
        except Exception as exc:
            print(f"[projects] failed to persist finding reasoning: {exc}")

        return result
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_REASON_ERROR_RESPONSE)


_TRANSFORM_ERROR_RESPONSE = {"error": "Could not generate a fix for this finding, please try again"}


@router.post("/projects/{project_id}/findings/transform", response_model=FindingTransform)
async def transform_finding(project_id: str, payload: FindingReasonRequest):
    try:
        project = await get_project(project_id)
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        findings = project.get("findings", [])
        if payload.finding_index < 0 or payload.finding_index >= len(findings):
            return JSONResponse(status_code=400, content={"error": "Invalid finding index"})

        finding = findings[payload.finding_index]

        code_snippet = _extract_code_snippet(project.get("files", []), finding.get("file", ""), finding.get("line", 0))
        if not code_snippet:
            code_snippet = finding.get("evidence", "")

        file_entry = next((f for f in project.get("files", []) if f.get("path") == finding.get("file")), None)
        language = (file_entry or {}).get("language") or "unknown"

        standard_id = RULE_TO_STANDARD.get(finding.get("rule"))
        matched_standards = [get_standard_by_id(standard_id)] if standard_id else []
        if not matched_standards:
            weight_category = FINDING_CATEGORY_MAP.get(finding.get("category"))
            if weight_category:
                matched_standards = get_standards_for(weight_category, language)[:2]

        result = await generate_fix(finding, code_snippet, language, matched_standards)

        try:
            findings[payload.finding_index]["transform"] = result.model_dump()
            await update_project(project_id, {"findings": findings})
        except Exception as exc:
            print(f"[projects] failed to persist finding transform: {exc}")

        return result
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_TRANSFORM_ERROR_RESPONSE)


_REANALYZE_ERROR_RESPONSE = {"error": "Could not reanalyze this project, please try again"}

_DERIVED_FIELDS = ("imports", "functions", "classes", "tests", "configs", "deploymentFiles", "findings", "warnings")


def _finding_keys(findings: list[dict]) -> set[tuple]:
    return {(f.get("file"), f.get("rule")) for f in findings}


def _verification_note(before_project: dict) -> str:
    # HONESTY RULE: this system never executes uploaded code, so it can never confirm
    # runtime behavior — only static findings + score can shift. Keep that caveat first,
    # always, no exceptions, no matter how good the after_score looks.
    note = (
        "No tests were executed — this system does not run code. This comparison "
        "reflects static analysis findings and score only, not confirmed runtime behavior."
    )
    tests = before_project.get("tests") or []
    if tests:
        note += f" This project has {len(tests)} detected test file(s), but they were not run by this system."
    return note


@router.post("/projects/{project_id}/reanalyze")
async def reanalyze_project(project_id: str, payload: FindingReasonRequest):
    try:
        project = await get_project(project_id)
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        findings = project.get("findings", [])
        if payload.finding_index < 0 or payload.finding_index >= len(findings):
            return JSONResponse(status_code=400, content={"error": "Invalid finding index"})

        finding = findings[payload.finding_index]
        transform = finding.get("transform")
        if not transform or not transform.get("proposed_fix"):
            return JSONResponse(status_code=400, content={"error": "Generate a fix for this finding first"})

        before_score = compute_score(project)

        patched = copy.deepcopy(project)

        file_entry = next((f for f in patched.get("files", []) if f.get("path") == finding.get("file")), None)
        content = file_entry.get("content") if file_entry else None
        if file_entry is None or content is None:
            return JSONResponse(
                status_code=400, content={"error": "Could not locate the original file content to apply the patch"}
            )

        original_snippet = transform.get("original_snippet", "")
        if not original_snippet or original_snippet not in content:
            return JSONResponse(
                status_code=400,
                content={"error": "Could not locate the original snippet in the file — it may have changed since the fix was generated"},
            )
        file_entry["content"] = content.replace(original_snippet, transform.get("proposed_fix", ""), 1)

        for key in _DERIVED_FIELDS:
            patched[key] = []

        analyze_project(patched)
        after_score = compute_score(patched)

        before_keys = _finding_keys(project.get("findings", []))
        after_keys = _finding_keys(patched.get("findings", []))

        resolved_findings = [f for f in project.get("findings", []) if (f.get("file"), f.get("rule")) not in after_keys]
        remaining_findings = [f for f in project.get("findings", []) if (f.get("file"), f.get("rule")) in after_keys]
        new_findings = [f for f in patched.get("findings", []) if (f.get("file"), f.get("rule")) not in before_keys]

        patched["compliance_score"] = after_score
        patched.pop("_id", None)  # let Mongo assign a fresh id — this must be a separate document
        session_id = project.get("session_id")
        new_project_id = await save_project(patched, session_id)

        return {
            "new_project_id": new_project_id,
            "before_score": before_score["overall_score"],
            "after_score": after_score["overall_score"],
            "resolved_findings": resolved_findings,
            "remaining_findings": remaining_findings,
            "new_findings": new_findings,
            "behavior_verified": False,
            "verification_note": _verification_note(project),
        }
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_REANALYZE_ERROR_RESPONSE)


_CHAT_ERROR_RESPONSE = {"error": "Could not answer this question, please try again"}


@router.post("/projects/{project_id}/chat")
async def chat_about_project(project_id: str, payload: ChatRequest):
    try:
        project = await get_project(project_id)
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        retrieved = retrieve_relevant_files(project, payload.question)

        if not retrieved:
            return {
                "answer": "This codebase doesn't appear to contain anything matching that question — "
                "no files matched the terms used.",
                "cited_files": [],
                "retrieved_files": [],
            }

        result = await answer_project_question(payload.question, retrieved)

        return {**result, "retrieved_files": [f["path"] for f in retrieved]}
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_CHAT_ERROR_RESPONSE)
