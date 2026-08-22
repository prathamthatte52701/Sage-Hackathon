import copy
import json
import os
import re
import zipfile
from io import BytesIO
from pathlib import PurePosixPath

import httpx
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response

from db.mongo import get_owned_project, save_project, update_owned_project
from models.schemas import ApplyProjectFixRequest, ChatRequest, DownloadProjectRequest, FindingReasonRequest, FindingReasoning, FindingTransform, GithubImportRequest
from knowledge.retrieval import build_finding_knowledge_query, retrieve_knowledge
from services.analyzer import SOURCE_LANGUAGES, analyze_project
from services.auth import get_current_user
from services.project_review import run_ai_quality_review
from services.context_expansion import build_finding_context
from services.reasoning_engine import answer_project_question, confirm_and_explain_finding, generate_fix
from services.patching import PatchError, apply_exact_replacement, make_unified_diff, safe_archive_path
from services.retrieval import retrieve_relevant_files, retrieve_semantic_project_context
from services.scoring import FINDING_CATEGORY_MAP, RULE_TO_STANDARD, compute_score
from services.standards import get_standard_by_id, get_standards_for

router = APIRouter()

MAX_ZIP_SIZE = 300 * 1024 * 1024  # 300MB
MAX_UNCOMPRESSED_SIZE = 600 * 1024 * 1024  # archive-bomb guard
MAX_SINGLE_FILE_UNCOMPRESSED = 15 * 1024 * 1024  # per-file decompressed cap, enforced on ACTUAL bytes read
MAX_FILE_COUNT = 2000
MAX_CONTENT_SIZE = 100_000  # chars; retained as the large-file warning threshold
MAX_PATH_DEPTH = 20

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

TEXT_MANIFEST_FILENAMES = {
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "setup.py",
    "pom.xml",
    "build.gradle",
    ".env.example",
    "tsconfig.json",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "render.yaml",
    "vercel.json",
    "Procfile",
}

_ERROR_RESPONSE = {"error": "Could not process the uploaded project, please try again"}


def _guess_language(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return EXTENSION_LANGUAGE_MAP.get(ext, "other")


def _is_unsafe_path(name: str) -> bool:
    """Reject path traversal, absolute paths, and Windows drive-letter paths."""
    normalized = name.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if ".." in parts:
        return True
    if len(parts) > MAX_PATH_DEPTH:
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


def _should_read_text(display_name: str, language: str) -> bool:
    basename = PurePosixPath(display_name.replace("\\", "/")).name
    return language in SOURCE_LANGUAGES or basename in TEXT_MANIFEST_FILENAMES


def _extract_dependencies(files_index: list[dict]) -> list[dict]:
    dependencies = []
    seen = set()

    def add(name: str, source: str, version: str = ""):
        clean_name = name.strip()
        if not clean_name or clean_name.startswith("#"):
            return
        key = (clean_name.lower(), source)
        if key in seen:
            return
        seen.add(key)
        dependencies.append({"name": clean_name, "version": version.strip(), "source": source})

    for file_entry in files_index:
        path = file_entry.get("path", "")
        content = file_entry.get("content") or ""
        basename = PurePosixPath(path.replace("\\", "/")).name
        if basename == "requirements.txt":
            for raw_line in content.splitlines():
                line = raw_line.split("#", 1)[0].strip()
                if not line or line.startswith(("-r ", "--")):
                    continue
                match = re.match(r"([A-Za-z0-9_.-]+)\s*([<>=!~].*)?$", line)
                if match:
                    add(match.group(1), path, match.group(2) or "")
        elif basename == "package.json":
            try:
                package = json.loads(content)
            except json.JSONDecodeError:
                continue
            for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                values = package.get(section)
                if isinstance(values, dict):
                    for name, version in values.items():
                        add(str(name), f"{path}:{section}", str(version))
    return dependencies


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

        # Cheap first pass on header-declared sizes -- catches an honest huge
        # archive before spending any CPU on decompression. NOT sufficient on
        # its own: a crafted entry can declare a small file_size in its
        # header while its actual deflate stream expands far larger, so the
        # per-file/running-total check below (on bytes actually read) is the
        # real enforcement layer against a forged-header zip bomb.
        total_uncompressed = sum(zf.getinfo(name).file_size for name in names)
        if total_uncompressed > MAX_UNCOMPRESSED_SIZE:
            return None, None, {"error": "ZIP uncompressed contents exceed the 600MB limit"}

        prefix = _strip_common_top_level(names) if strip_top_level else ""

        files_index = []
        ignored_counts: dict[str, int] = {}
        actual_uncompressed_total = 0

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
            if _should_read_text(display_name, language):
                with zf.open(name) as entry:
                    raw = entry.read(MAX_SINGLE_FILE_UNCOMPRESSED + 1)
                if len(raw) > MAX_SINGLE_FILE_UNCOMPRESSED:
                    return None, None, {"error": f"{display_name}: file too large after decompression"}
                actual_uncompressed_total += len(raw)
                if actual_uncompressed_total > MAX_UNCOMPRESSED_SIZE:
                    return None, None, {"error": "ZIP uncompressed contents exceed the 600MB limit"}
                content = raw.decode("utf-8", errors="replace")

            files_index.append(
                {
                    "path": display_name,
                    "language": language,
                    "size": info.file_size,
                    "content": content,
                    "large_file": bool(content is not None and len(content) > MAX_CONTENT_SIZE),
                }
            )

    warnings = [f"skipped {count} file(s) under {dirname}/" for dirname, count in ignored_counts.items()]
    warnings.extend(
        f"{f['path']}: large source file preserved for deterministic scan ({len(f.get('content') or '')} chars)"
        for f in files_index
        if f.get("large_file")
    )

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
        "dependencies": _extract_dependencies(files_index),
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


async def _read_upload_capped(file: UploadFile, max_size: int) -> bytes | None:
    """Reads in bounded chunks so an oversized body is rejected without ever
    buffering the whole thing in memory first -- unlike a single
    `await file.read()`, whose cost is paid before MAX_ZIP_SIZE is checked."""
    chunks = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/projects/upload")
async def upload_project(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    current_user: dict = Depends(get_current_user),
):
    try:
        raw_bytes = await _read_upload_capped(file, MAX_ZIP_SIZE)
        if raw_bytes is None:
            return JSONResponse(status_code=400, content={"error": "ZIP file exceeds the 300MB limit"})

        project_representation, warnings, error = _project_from_zip_bytes(
            raw_bytes, _derive_project_name(file.filename)
        )
        if error is not None:
            return JSONResponse(status_code=400, content=error)

        project_id = await save_project(project_representation, session_id, current_user["_id"])

        print(f"[projects] upload user_id={current_user['_id']} project_id={project_id}")
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
async def import_from_github(payload: GithubImportRequest, current_user: dict = Depends(get_current_user)):
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

        project_id = await save_project(project_representation, payload.session_id, current_user["_id"])

        print(f"[projects] upload user_id={current_user['_id']} project_id={project_id}")
        return {"project_id": project_id, "project": project_representation, "warnings": warnings}
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_GITHUB_ERROR_RESPONSE)


@router.get("/projects/{project_id}")
async def get_project_by_id(project_id: str, current_user: dict = Depends(get_current_user)):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        return project
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_ERROR_RESPONSE)


_ANALYZE_ERROR_RESPONSE = {"error": "Could not analyze this project, please try again"}


@router.post("/projects/{project_id}/analyze")
async def analyze_project_by_id(project_id: str, current_user: dict = Depends(get_current_user)):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        analyzed = analyze_project(project)

        # Phase 13: project analysis previously stopped at deterministic
        # regex rules -- no AI quality review, no RAG, no grounding, making
        # it meaningfully shallower than paste-code review. Run the same
        # quality-review stage against this project's own source files,
        # bounded/concurrency-limited so a large project doesn't trigger
        # hundreds of uncontrolled Groq calls. A failure here degrades
        # gracefully -- deterministic findings above are unaffected.
        try:
            coverage = await run_ai_quality_review(analyzed)
            print(f"[projects] AI quality review coverage: {coverage}")
        except Exception as exc:
            print(f"[projects] AI quality review failed, continuing with deterministic findings only: {exc}")

        updates = {
            key: analyzed.get(key, [])
            for key in (
                "dependencies",
                "imports",
                "functions",
                "classes",
                "apiEndpoints",
                "tests",
                "configs",
                "deploymentFiles",
                "findings",
            "warnings",
            "structuralMetadata",
        )
        }
        updates["ai_review_coverage"] = analyzed.get("ai_review_coverage", {})
        await update_owned_project(project_id, current_user["_id"], updates)

        return analyzed
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_ANALYZE_ERROR_RESPONSE)


_SCORE_ERROR_RESPONSE = {"error": "Could not score this project, please try again"}


@router.post("/projects/{project_id}/score")
async def score_project_by_id(project_id: str, current_user: dict = Depends(get_current_user)):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        score = compute_score(project)
        await update_owned_project(project_id, current_user["_id"], {"compliance_score": score})

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
async def reason_about_finding(
    project_id: str, payload: FindingReasonRequest, current_user: dict = Depends(get_current_user)
):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        findings = project.get("findings", [])
        if payload.finding_index < 0 or payload.finding_index >= len(findings):
            return JSONResponse(status_code=400, content={"error": "Invalid finding index"})

        finding = findings[payload.finding_index]

        context = build_finding_context(project, finding)
        code_snippet = context["snippet"] or finding.get("evidence", "")
        language = context["language"]

        # Prefer the rule's directly-mapped standard; the citation is attached
        # server-side (not trusted from the LLM output) so it's always accurate.
        standard_id = RULE_TO_STANDARD.get(finding.get("rule"))
        matched_standards = [get_standard_by_id(standard_id)] if standard_id else []
        if not matched_standards:
            weight_category = FINDING_CATEGORY_MAP.get(finding.get("category"))
            if weight_category:
                matched_standards = get_standards_for(weight_category, language)[:2]

        weight_category = FINDING_CATEGORY_MAP.get(finding.get("category"))
        knowledge_query = build_finding_knowledge_query(
            finding,
            surrounding_context=code_snippet,
            detector_name=finding.get("rule"),
        )
        knowledge = await retrieve_knowledge(
            knowledge_query,
            language=language,
            frameworks=project.get("project", {}).get("frameworks", []),
            category=weight_category,
            exact_rule_id=finding.get("rule"),
        )

        result = await confirm_and_explain_finding(
            finding,
            code_snippet,
            language,
            matched_standards,
            related_files=context["related_files"],
            knowledge=knowledge,
        )

        try:
            findings[payload.finding_index]["reasoning"] = result.model_dump()
            findings[payload.finding_index]["knowledge_retrieval"] = {
                "mode": knowledge.get("mode"),
                "available": knowledge.get("available"),
                "record_count": len(knowledge.get("records", [])),
                "rule_ids": [r.get("rule_id") for r in knowledge.get("records", [])],
            }
            findings[payload.finding_index]["related_files"] = [f["path"] for f in context["related_files"]]
            await update_owned_project(project_id, current_user["_id"], {"findings": findings})
        except Exception as exc:
            print(f"[projects] failed to persist finding reasoning: {exc}")

        return result
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_REASON_ERROR_RESPONSE)


_TRANSFORM_ERROR_RESPONSE = {"error": "Could not generate a fix for this finding, please try again"}


def _enrich_transform(transform: FindingTransform, finding: dict, content: str | None = None) -> FindingTransform:
    original = transform.original_snippet or transform.original_code
    fixed = transform.proposed_fix or transform.fixed_code
    diff = make_unified_diff(original, fixed, finding.get("file") or "file") if original and fixed else ""
    can_apply = False
    if content is not None and original and fixed:
        try:
            apply_exact_replacement(content, original, fixed)
            can_apply = True
        except PatchError:
            can_apply = False
    transform.finding_id = f"{finding.get('file', '')}:{finding.get('line', '')}:{finding.get('rule', '')}"
    transform.rule_id = finding.get("rule", "")
    transform.file = finding.get("file", "")
    transform.line = int(finding.get("line") or 0)
    transform.summary = transform.summary or (transform.explanation.split(".")[0] if transform.explanation else "Focused code change generated.")
    transform.explanation_bullets = transform.explanation_bullets or [
        part.strip("- ").strip() for part in (transform.explanation or "").split(".") if part.strip()
    ][:4]
    transform.original_code = original
    transform.fixed_code = fixed
    transform.diff = diff
    transform.can_apply = can_apply
    return transform


@router.post("/projects/{project_id}/findings/transform", response_model=FindingTransform)
async def transform_finding(
    project_id: str, payload: FindingReasonRequest, current_user: dict = Depends(get_current_user)
):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        findings = project.get("findings", [])
        if payload.finding_index < 0 or payload.finding_index >= len(findings):
            return JSONResponse(status_code=400, content={"error": "Invalid finding index"})

        finding = findings[payload.finding_index]

        context = build_finding_context(project, finding)
        code_snippet = context["snippet"] or finding.get("evidence", "")
        language = context["language"]

        standard_id = RULE_TO_STANDARD.get(finding.get("rule"))
        matched_standards = [get_standard_by_id(standard_id)] if standard_id else []
        if not matched_standards:
            weight_category = FINDING_CATEGORY_MAP.get(finding.get("category"))
            if weight_category:
                matched_standards = get_standards_for(weight_category, language)[:2]

        weight_category = FINDING_CATEGORY_MAP.get(finding.get("category"))
        knowledge_query = build_finding_knowledge_query(
            finding,
            surrounding_context=code_snippet,
            detector_name=finding.get("rule"),
        )
        knowledge = await retrieve_knowledge(
            knowledge_query,
            language=language,
            frameworks=project.get("project", {}).get("frameworks", []),
            category=weight_category,
            exact_rule_id=finding.get("rule"),
        )

        result = await generate_fix(
            finding,
            code_snippet,
            language,
            matched_standards,
            related_files=context["related_files"],
            knowledge=knowledge,
        )
        file_entry = next((f for f in project.get("files", []) if f.get("path") == finding.get("file")), None)
        result = _enrich_transform(result, finding, file_entry.get("content") if file_entry else None)

        try:
            findings[payload.finding_index]["transform"] = result.model_dump()
            await update_owned_project(project_id, current_user["_id"], {"findings": findings})
        except Exception as exc:
            print(f"[projects] failed to persist finding transform: {exc}")

        return result
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_TRANSFORM_ERROR_RESPONSE)


_REANALYZE_ERROR_RESPONSE = {"error": "Could not reanalyze this project, please try again"}

_DERIVED_FIELDS = (
    "imports",
    "functions",
    "classes",
    "apiEndpoints",
    "tests",
    "configs",
    "deploymentFiles",
    "findings",
    "warnings",
    "structuralMetadata",
)


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
async def reanalyze_project(
    project_id: str, payload: FindingReasonRequest, current_user: dict = Depends(get_current_user)
):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
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
        new_project_id = await save_project(patched, session_id, current_user["_id"])

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


_APPLY_ERROR_RESPONSE = {"error": "Could not apply this fix safely"}
_DOWNLOAD_ERROR_RESPONSE = {"error": "Could not create fixed ZIP"}


@router.post("/projects/{project_id}/fixes/apply")
async def apply_project_fix(
    project_id: str, payload: ApplyProjectFixRequest, current_user: dict = Depends(get_current_user)
):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        findings = project.get("findings", [])
        if payload.finding_index < 0 or payload.finding_index >= len(findings):
            return JSONResponse(status_code=400, content={"error": "Invalid finding index"})

        finding = findings[payload.finding_index]
        transform = finding.get("transform") or {}
        original = transform.get("original_snippet") or transform.get("original_code") or ""
        fixed = transform.get("proposed_fix") or transform.get("fixed_code") or ""
        if not original or not fixed:
            return JSONResponse(status_code=400, content={"error": "Generate a fix before applying it"})

        file_entry = next((f for f in project.get("files", []) if f.get("path") == finding.get("file")), None)
        if not file_entry or file_entry.get("content") is None:
            return JSONResponse(status_code=400, content={"error": "Could not locate target file content"})

        try:
            applied = apply_exact_replacement(file_entry["content"], original, fixed)
        except PatchError as exc:
            finding["fix_state"] = "Conflict"
            await update_owned_project(project_id, current_user["_id"], {"findings": findings})
            return JSONResponse(status_code=409, content={"error": str(exc)})

        file_entry["content"] = applied.patched
        finding["fix_state"] = "Applied"
        finding["applied_patch"] = {
            "file": finding.get("file"),
            "original_code": original,
            "fixed_code": fixed,
            "diff": applied.diff,
        }
        project.setdefault("patches", [])
        project["patches"].append(
            {
                "finding_index": payload.finding_index,
                "rule_id": finding.get("rule"),
                "file": finding.get("file"),
                "diff": applied.diff,
                "state": "Applied",
            }
        )

        for key in _DERIVED_FIELDS:
            project[key] = [] if key != "findings" else findings
        analyze_project(project)
        after_score = compute_score(project)
        project["compliance_score"] = after_score
        await update_owned_project(
            project_id,
            current_user["_id"],
            {"files": project["files"], "findings": project["findings"], "patches": project.get("patches", []), "compliance_score": after_score},
        )
        print(f"[projects] fix applied user_id={current_user['_id']} project_id={project_id}")
        return {
            "status": "applied",
            "file": finding.get("file"),
            "modified_files": sorted({p.get("file") for p in project.get("patches", []) if p.get("file")}),
            "after_score": after_score,
            "verification": "Reanalyzed with static detectors after applying patch.",
        }
    except Exception as exc:
        print(f"[projects] apply fix error: {exc}")
        return JSONResponse(status_code=500, content=_APPLY_ERROR_RESPONSE)


@router.get("/projects/{project_id}/download-fixed")
async def download_fixed_project(
    project_id: str, filename: str | None = None, current_user: dict = Depends(get_current_user)
):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_entry in project.get("files", []):
                path = safe_archive_path(file_entry.get("path", ""))
                first = PurePosixPath(path).parts[0] if PurePosixPath(path).parts else ""
                if first in IGNORE_DIRS or path.endswith((".env", ".pyc")):
                    continue
                content = file_entry.get("content")
                if content is None:
                    continue
                zf.writestr(path, content)
        buffer.seek(0)
        print(f"[projects] download user_id={current_user['_id']} project_id={project_id}")
        project_name = project.get("project", {}).get("name") or "project"
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", filename or f"{project_name}-code-master-ai-fixed.zip").strip("-")
        if not safe_name.endswith(".zip"):
            safe_name += ".zip"
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
        )
    except PatchError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception as exc:
        print(f"[projects] download fixed zip error: {exc}")
        return JSONResponse(status_code=500, content=_DOWNLOAD_ERROR_RESPONSE)


_CHAT_ERROR_RESPONSE = {"error": "Could not answer this question, please try again"}

# Heuristic for "this question wants general engineering guidance" (production
# readiness, security posture, architecture/scalability advice) vs. a plain
# "where is X" lookup. Only guidance-shaped questions pay the extra knowledge
# retrieval — a file lookup doesn't need production-readiness standards.
_GUIDANCE_KEYWORDS = {
    "production", "ready", "readiness", "secure", "security", "vulnerab", "scale",
    "scalab", "architecture", "database", "deploy", "deployment", "improve",
    "improvement", "best practice", "reliab", "performance", "risky", "risk",
}


def _looks_like_guidance_question(question: str) -> bool:
    q = question.lower()
    return any(keyword in q for keyword in _GUIDANCE_KEYWORDS)


@router.post("/projects/{project_id}/chat")
async def chat_about_project(project_id: str, payload: ChatRequest, current_user: dict = Depends(get_current_user)):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        # Stage 1/2 (unchanged): deterministic keyword/import retrieval is the
        # sole source of PROJECT EVIDENCE and always runs first.
        retrieved = retrieve_relevant_files(project, payload.question)

        if not retrieved:
            return {
                "answer": "This codebase doesn't appear to contain anything matching that question — "
                "no files matched the terms used.",
                "cited_files": [],
                "retrieved_files": [],
            }

        # Stage 3 (optional, additive): engineering knowledge for guidance-shaped
        # questions, and cross-project semantic background context. Both are
        # best-effort enrichment — retrieve_knowledge already fails to a
        # deterministic fallback internally, and retrieve_semantic_project_context
        # fails silently to []. Neither can break the chat response below.
        knowledge = None
        if _looks_like_guidance_question(payload.question):
            try:
                project_meta = project.get("project", {})
                languages = project_meta.get("languages") or []
                knowledge = await retrieve_knowledge(
                    payload.question,
                    language=languages[0] if languages else None,
                    frameworks=project_meta.get("frameworks", []),
                    top_k=3,
                )
            except Exception as exc:
                print(f"[projects] chat knowledge retrieval failed, continuing without it: {exc}")
                knowledge = None

        semantic_context = await retrieve_semantic_project_context(project, payload.question, top_k=2)

        result = await answer_project_question(payload.question, retrieved, knowledge, semantic_context)

        return {
            **result,
            "retrieved_files": [f["path"] for f in retrieved],
            "knowledge_retrieval": (
                {
                    "mode": knowledge.get("mode"),
                    "available": knowledge.get("available"),
                    "record_count": len(knowledge.get("records", [])),
                }
                if knowledge
                else None
            ),
            "semantic_project_context": [
                {"name": p.get("name"), "similarity": round(p.get("similarity", 0), 3)} for p in semantic_context
            ],
        }
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_CHAT_ERROR_RESPONSE)
