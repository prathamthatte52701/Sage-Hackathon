import copy
import asyncio
import json
import os
import re
import tempfile
import time
import zipfile
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath

import httpx
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse, Response, StreamingResponse

from db.mongo import fetch_binary_content, get_owned_project, get_owned_project_file, get_owned_project_metadata, save_project, update_owned_finding, update_owned_project
from models.schemas import ApplyProjectFixRequest, ChatRequest, DownloadProjectRequest, FindingReasonRequest, FindingReasoning, FindingTransform, GithubImportRequest
from knowledge.retrieval import build_finding_knowledge_query, retrieve_knowledge
from services.analyzer import SOURCE_LANGUAGES, analyze_project
from services.auth import get_request_user
from services.blast_radius import build_blast_radius
from services.brutal_audit import run_brutal_audit
from services.fix_all import get_fix_all_status, get_fix_all_status_with_recovery, is_fix_all_running, request_stop, start_fix_all
from services.hacker_lens import run_hacker_lens
from services.project_review import run_ai_quality_review
from services.context_expansion import build_finding_context
from services.reasoning_engine import answer_project_question, confirm_and_explain_finding, generate_fix
from services.patching import PatchError, apply_exact_replacement, apply_structured_patch, build_patch_metadata, make_unified_diff, safe_archive_path
from services.retrieval import retrieve_relevant_files, retrieve_semantic_project_context
from services.security_rules import to_closed_world_findings
from services.scoring import FINDING_CATEGORY_MAP, RULE_TO_STANDARD, compute_score
from services.standards import get_standard_by_id, get_standards_for
from services.analysis_jobs import enqueue_analysis, get_analysis_job_with_recovery
# V2_AUTOMATION_DISABLED:
# Automation is intentionally excluded from CODE MASTER AI V1.
# Preserve this code for the V2 automation workflow.
# from services.automation import (
#     get_automation_status,
#     is_automation_running,
#     request_stop as request_automation_stop,
#     start_automation,
# )
from services.commit_guard import get_commit_guard_status, start_commit_guard
from services.pr_guard import get_pr_guard_status, start_pr_guard

router = APIRouter()


class PRGuardRequest(BaseModel):
    pull_request_number: int = Field(..., ge=1, le=999999)

MAX_ZIP_SIZE = 300 * 1024 * 1024  # 300MB
MAX_UNCOMPRESSED_SIZE = 600 * 1024 * 1024  # archive-bomb guard
MAX_SINGLE_FILE_UNCOMPRESSED = 15 * 1024 * 1024  # per-file decompressed cap, enforced on ACTUAL bytes read
# Applies to ELIGIBLE files only (after junk-directory and binary/asset
# filtering below) -- NOT the raw ZIP entry count. A repo with 12,000 raw
# entries but 3,000 real source files (the rest node_modules/.git/build
# noise) must not be rejected just because the raw count is large.
MAX_REPOSITORY_FILES = 5000
MAX_CONTENT_SIZE = 100_000  # chars; retained as the large-file warning threshold
MAX_PATH_DEPTH = 20

IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__",
    "dist", "build", "out", "coverage", ".cache",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".idea", ".vscode", "tmp", "temp", "logs",
    "target", "bin", "obj", "vendor",
}
# Narrower than a whole ignored top-level directory: only the generated
# cache subtree of Next.js's .next/ is junk -- the rest of .next/ (and any
# other unlisted directory) is left alone, per "be conservative" above.
IGNORE_PATH_PREFIXES = (".next/cache/",)

# Assets CODE MASTER AI cannot meaningfully analyze as source. These are still stored
# (for byte-exact download-fixed-ZIP fidelity -- GridFS/binary_content,
# unchanged from today) but never counted toward MAX_REPOSITORY_FILES and
# never sent to any AI/RAG context, matching existing _should_read_text
# behavior for non-source extensions.
BINARY_ASSET_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".mp4", ".mov", ".mp3", ".wav",
    ".pdf",
    ".zip", ".tar", ".gz",
    ".exe", ".dll", ".so", ".dylib",
    ".class", ".pyc",
    ".map",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
}

EXTENSION_LANGUAGE_MAP = {
    ".py": "python",
    ".pyi": "python",
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
    "Pipfile",
}

# Generic config/deployment file shapes worth reading as text even though
# they aren't a programming "language" -- deliberately kept out of
# EXTENSION_LANGUAGE_MAP/SOURCE_LANGUAGES so they never show up as a
# detected project language or get routed through language-specific
# analysis; they just stop being treated as an opaque binary blob.
TEXT_CONFIG_EXTENSIONS = {".yaml", ".yml", ".toml", ".cfg"}

# Upload/import bodies spool to RAM up to this size, then transparently
# spill to disk -- same threshold download_fixed_project already uses for
# the output side of this file.
UPLOAD_SPOOL_THRESHOLD = 8 * 1024 * 1024

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


def _canonical_archive_path(name: str) -> str:
    """Normalize safe archive names to the single form used in storage."""
    return str(PurePosixPath((name or "").replace("\\", "/")))


def _should_read_text(display_name: str, language: str) -> bool:
    basename = PurePosixPath(display_name.replace("\\", "/")).name
    if language in SOURCE_LANGUAGES or basename in TEXT_MANIFEST_FILENAMES:
        return True
    if basename.startswith("README"):
        return True
    return os.path.splitext(basename)[1].lower() in TEXT_CONFIG_EXTENSIONS


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
    return _ignore_label(name) is not None


def _ignore_label(name: str) -> str | None:
    """The junk directory/prefix responsible for ignoring this path, or None."""
    normalized = name.replace("\\", "/")
    for prefix in IGNORE_PATH_PREFIXES:
        if normalized.startswith(prefix):
            return prefix.rstrip("/")
    return next((part for part in PurePosixPath(normalized).parts if part in IGNORE_DIRS), None)


def _is_binary_asset(display_name: str) -> bool:
    return os.path.splitext(display_name)[1].lower() in BINARY_ASSET_EXTENSIONS


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


def _project_from_zip_bytes(zip_source: bytes | tempfile.SpooledTemporaryFile, project_name: str, strip_top_level: bool = False):
    """Shared by ZIP upload and GitHub import: one normalized project
    representation, one analysis pipeline downstream — never two.

    zip_source is either raw bytes (existing tests, small callers) or an
    already-seekable file-like object -- the SpooledTemporaryFile the
    production upload/import paths now stream into, so this function never
    has to make its own BytesIO(raw_bytes) copy of a near-cap archive.

    Returns (project_representation, upload_warnings, error_response). Exactly
    one of (project_representation, error_response) is None.
    """
    if isinstance(zip_source, (bytes, bytearray)):
        if len(zip_source) > MAX_ZIP_SIZE:
            return None, None, {"error": "ZIP file exceeds the 300MB limit"}
        buffer = BytesIO(zip_source)
    else:
        buffer = zip_source
        buffer.seek(0, os.SEEK_END)
        if buffer.tell() > MAX_ZIP_SIZE:
            return None, None, {"error": "ZIP file exceeds the 300MB limit"}
        buffer.seek(0)

    if not zipfile.is_zipfile(buffer):
        return None, None, {"error": "Uploaded file is not a valid ZIP archive"}

    with zipfile.ZipFile(buffer) as zf:
        names = zf.namelist()

        if any(_is_unsafe_path(name) for name in names):
            return None, None, {"error": "ZIP contains unsafe file paths"}

        prefix = _strip_common_top_level(names) if strip_top_level else ""

        # Classify by path/extension alone -- no decompression needed yet.
        # Only files that are neither in a junk directory nor an obviously
        # binary/noise asset count toward MAX_REPOSITORY_FILES; this is what
        # lets a repo with thousands of raw node_modules/.git entries still
        # be accepted when its real source footprint is small. Rejecting
        # here, before opening a single entry, is also the cheapest possible
        # place to bail out of an oversized repository.
        eligible_paths: set[str] = set()
        for name in names:
            if name.endswith("/"):
                continue
            display_name = name[len(prefix):] if prefix and name.startswith(prefix) else name
            display_name = _canonical_archive_path(display_name)
            if not display_name or _is_ignored(display_name):
                continue
            if _is_binary_asset(display_name):
                continue
            eligible_paths.add(display_name)

        if len(eligible_paths) > MAX_REPOSITORY_FILES:
            return None, None, {
                "error": (
                    f"Repository contains {len(eligible_paths):,} analyzable files. "
                    f"Current maximum is {MAX_REPOSITORY_FILES:,}. "
                    "Dependency/build/cache files were already excluded."
                )
            }

        # Cheap first pass on header-declared sizes -- catches an honest huge
        # archive before spending any CPU on decompression. NOT sufficient on
        # its own: a crafted entry can declare a small file_size in its
        # header while its actual deflate stream expands far larger, so the
        # per-file/running-total check below (on bytes actually read) is the
        # real enforcement layer against a forged-header zip bomb.
        total_uncompressed = sum(zf.getinfo(name).file_size for name in names)
        if total_uncompressed > MAX_UNCOMPRESSED_SIZE:
            return None, None, {"error": "ZIP uncompressed contents exceed the 600MB limit"}

        files_index = []
        stored_paths: set[str] = set()
        ignored_counts: dict[str, int] = {}
        actual_uncompressed_total = 0

        for name in names:
            if name.endswith("/"):
                continue  # directory entry

            display_name = name[len(prefix):] if prefix and name.startswith(prefix) else name
            display_name = _canonical_archive_path(display_name)
            if not display_name:
                continue

            if display_name in stored_paths:
                return None, None, {"error": "ZIP contains duplicate file paths"}

            ignore_label = _ignore_label(display_name)
            if ignore_label is not None:
                ignored_counts[ignore_label] = ignored_counts.get(ignore_label, 0) + 1
                continue

            stored_paths.add(display_name)

            info = zf.getinfo(name)
            language = _guess_language(display_name)

            with zf.open(name) as entry:
                raw = entry.read(MAX_SINGLE_FILE_UNCOMPRESSED + 1)
            if len(raw) > MAX_SINGLE_FILE_UNCOMPRESSED:
                return None, None, {"error": f"{display_name}: file too large after decompression"}
            actual_uncompressed_total += len(raw)
            if actual_uncompressed_total > MAX_UNCOMPRESSED_SIZE:
                return None, None, {"error": "ZIP uncompressed contents exceed the 600MB limit"}
            content = raw.decode("utf-8", errors="replace") if _should_read_text(display_name, language) else None

            files_index.append(
                {
                    "path": display_name,
                    "language": language,
                    "size": info.file_size,
                    "content": content,
                    "binary_content": raw if content is None else None,
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


async def _read_upload_capped(file: UploadFile, max_size: int) -> tempfile.SpooledTemporaryFile | None:
    """Streams the upload in bounded chunks straight into a spooled temp file
    (RAM up to UPLOAD_SPOOL_THRESHOLD, disk beyond it) so an oversized body
    is rejected without ever buffering the whole thing in memory first --
    unlike a single `await file.read()` (whose cost is paid before
    MAX_ZIP_SIZE is checked), and unlike the old chunks-list-then-`b"".join`
    approach, which still ended up holding the entire joined body as one
    Python bytes object even though it read in bounded chunks."""
    spool = tempfile.SpooledTemporaryFile(max_size=UPLOAD_SPOOL_THRESHOLD, mode="w+b")
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            spool.close()
            return None
        spool.write(chunk)
    spool.seek(0)
    return spool


@router.post("/projects/upload")
async def upload_project(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    current_user: dict = Depends(get_request_user),
):
    stage_start = time.monotonic()
    print(f"[stage] UPLOAD_START user_id={current_user['_id']} filename={file.filename!r}")
    try:
        spool = await _read_upload_capped(file, MAX_ZIP_SIZE)
        if spool is None:
            return JSONResponse(status_code=400, content={"error": "ZIP file exceeds the 300MB limit"})

        try:
            project_representation, warnings, error = _project_from_zip_bytes(
                spool, _derive_project_name(file.filename)
            )
        finally:
            spool.close()
        if error is not None:
            return JSONResponse(status_code=400, content=error)

        eligible_count = len(project_representation.get("files", []))
        print(f"[stage] UPLOAD_FILTER_COMPLETE eligible_files={eligible_count} duration_ms={round((time.monotonic() - stage_start) * 1000)}")

        gridfs_start = time.monotonic()
        print(f"[stage] GRIDFS_STORE_START files={eligible_count}")
        project_id = await save_project(project_representation, session_id, current_user["_id"])
        print(f"[stage] GRIDFS_STORE_COMPLETE project_id={project_id} duration_ms={round((time.monotonic() - gridfs_start) * 1000)}")
        for file_entry in project_representation["files"]:
            file_entry.pop("binary_content", None)

        print(f"[stage] UPLOAD_COMPLETE project_id={project_id} eligible_files={eligible_count} total_duration_ms={round((time.monotonic() - stage_start) * 1000)}")
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
async def import_from_github(payload: GithubImportRequest, current_user: dict = Depends(get_request_user)):
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
        # httpx already buffered the response as one `resp.content` bytes object
        # (a streamed, bounded re-download is a separate concern from this P0)
        # -- spooling it here at least avoids _project_from_zip_bytes needing
        # its own BytesIO(raw_bytes) copy on top of that.
        spool = tempfile.SpooledTemporaryFile(max_size=UPLOAD_SPOOL_THRESHOLD, mode="w+b")
        spool.write(resp.content)
        spool.seek(0)
        try:
            project_representation, warnings, error = _project_from_zip_bytes(
                spool, repo, strip_top_level=True
            )
        finally:
            spool.close()
        if error is not None:
            return JSONResponse(status_code=400, content=error)

        # Commit Guard's only supported source: without owner/repo persisted
        # here, there is no way to later resolve real commit history for
        # this project at all. The zipball itself carries no git metadata.
        project_representation["github_owner"] = owner
        project_representation["github_repo"] = repo

        project_id = await save_project(project_representation, payload.session_id, current_user["_id"])
        for file_entry in project_representation["files"]:
            file_entry.pop("binary_content", None)

        print(f"[projects] upload user_id={current_user['_id']} project_id={project_id}")
        return {"project_id": project_id, "project": project_representation, "warnings": warnings}
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_GITHUB_ERROR_RESPONSE)


@router.get("/projects/{project_id}")
async def get_project_by_id(project_id: str, current_user: dict = Depends(get_request_user)):
    try:
        project = await get_owned_project_metadata(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        return project
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_ERROR_RESPONSE)


@router.get("/projects/{project_id}/metadata")
async def get_project_metadata(project_id: str, current_user: dict = Depends(get_request_user)):
    project = await get_owned_project_metadata(project_id, current_user["_id"])
    if project is None:
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    return project


@router.get("/projects/{project_id}/files/{file_path:path}")
async def get_project_file(project_id: str, file_path: str, current_user: dict = Depends(get_request_user)):
    file_entry = await get_owned_project_file(project_id, current_user["_id"], file_path)
    if file_entry is None:
        return JSONResponse(status_code=404, content={"error": "Project file not found"})
    return file_entry


_ANALYZE_ERROR_RESPONSE = {"error": "Could not analyze this project, please try again"}


def _finding_id(finding: dict) -> str:
    """Stable across wording changes and finding list reordering."""
    evidence = " ".join((finding.get("evidence") or "").split()).lower()
    parts = (finding.get("rule") or "", finding.get("file") or "", str(finding.get("line") or 0), evidence)
    return sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]


def _assign_finding_ids(findings: list[dict]) -> None:
    for finding in findings:
        finding.setdefault("finding_id", _finding_id(finding))


def _resolve_finding(findings: list[dict], finding_index: int, finding_id: str = "") -> tuple[int, dict] | tuple[None, None]:
    _assign_finding_ids(findings)
    if finding_id:
        for index, finding in enumerate(findings):
            if finding.get("finding_id") == finding_id:
                return index, finding
        return None, None
    if 0 <= finding_index < len(findings):
        return finding_index, findings[finding_index]
    return None, None


async def _run_project_analysis(project_id: str, owner_user_id: str) -> dict:
    """Canonical analysis pipeline used by both initial analysis and reanalysis."""
    stage_start = time.monotonic()
    print(f"[stage] ANALYSIS_START project_id={project_id}")
    project = await get_owned_project(project_id, owner_user_id)
    if project is None:
        raise LookupError("Project disappeared before analysis started")
    hydrated_bytes = sum(len(f.get("content") or "") for f in project.get("files", []))
    print(f"[stage] ANALYSIS_HYDRATED project_id={project_id} hydrated_files={len(project.get('files', []))} hydrated_bytes={hydrated_bytes}")

    # AST/regex/taint work is CPU-bound. Keep the event loop available for
    # health checks and other users while a large project is being scanned.
    analyzed = await asyncio.to_thread(analyze_project, project)
    try:
        coverage = await run_ai_quality_review(analyzed)
    except Exception as exc:
        print(f"[projects] AI quality review failed, retaining deterministic findings: {type(exc).__name__}")
        coverage = {
            "semantic_coverage": "partial",
            "partial_reasons": ["AI quality review failed"],
            "failed_ai_chunks": 0,
        }
        analyzed["ai_review_coverage"] = coverage
    _assign_finding_ids(analyzed.get("findings", []))
    # Phase 1 closed-world gate: additive, computed from the full (mixed
    # deterministic + AI-quality) findings list. Only findings whose rule
    # maps to one of the 12 locked SEC-* families with a real file/line
    # survive -- nothing AI-produced can pass (see services/security_rules.py).
    # `findings` itself is untouched so existing scoring/UI keep working;
    # later phases switch the primary product surface to this field.
    analyzed["all_findings"] = analyzed.get("findings", [])
    analyzed["security_findings"] = to_closed_world_findings(analyzed.get("findings", []))
    _assign_finding_ids(analyzed["security_findings"])
    analyzed["findings"] = analyzed["security_findings"]

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
            "all_findings",
            "warnings",
            "structuralMetadata",
            "security_findings",
        )
    }
    updates.update(
        {
            "ai_review_coverage": coverage,
            "analysis_status": "partial" if coverage.get("semantic_coverage") == "partial" else "completed",
            "analysis_revision": project.get("source_revision", 0),
        }
    )
    committed = await update_owned_project(
        project_id,
        owner_user_id,
        updates,
        expected_source_revision=int(project.get("source_revision", 0)),
    )
    if not committed:
        # A source-changing request won the race while this job was running.
        # Never label its old findings as analysis of the newer source.
        print(f"[stage] ANALYSIS_COMPLETE project_id={project_id} stale=true duration_ms={round((time.monotonic() - stage_start) * 1000)}")
        return {
            "project_id": project_id,
            "finding_count": 0,
            "analysis_revision": project.get("source_revision", 0),
            "partial": True,
            "stale": True,
        }
    print(
        f"[stage] ANALYSIS_COMPLETE project_id={project_id} finding_count={len(analyzed.get('security_findings', []))} "
        f"analysis_revision={updates['analysis_revision']} partial={updates['analysis_status'] == 'partial'} "
        f"duration_ms={round((time.monotonic() - stage_start) * 1000)}"
    )
    return {
        "project_id": project_id,
        "finding_count": len(analyzed.get("security_findings", [])),
        "analysis_revision": updates["analysis_revision"],
        "partial": updates["analysis_status"] == "partial",
    }


@router.post("/projects/{project_id}/analyze")
async def analyze_project_by_id(project_id: str, current_user: dict = Depends(get_request_user)):
    try:
        project = await get_owned_project_metadata(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        # V2_AUTOMATION_DISABLED:
        # Automation is intentionally excluded from CODE MASTER AI V1.
        # Preserve this code for the V2 automation workflow.
        # if is_automation_running(project_id):
        #     return JSONResponse(status_code=409, content={"error": "Automation is currently running for this project. Wait for it to finish before starting manual analysis."})
        job, created = await enqueue_analysis(
            project_id,
            current_user["_id"],
            lambda _job_id: _run_project_analysis(project_id, current_user["_id"]),
        )
        return JSONResponse(
            status_code=202,
            content={"job_id": job["_id"], "status": job.get("status", "queued"), "created": created},
        )
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_ANALYZE_ERROR_RESPONSE)


@router.get("/analysis-jobs/{job_id}")
async def get_analysis_job(job_id: str, current_user: dict = Depends(get_request_user)):
    job = await get_analysis_job_with_recovery(job_id, current_user["_id"])
    if job is None:
        return JSONResponse(status_code=404, content={"error": "Analysis job not found"})
    return job


_SCORE_ERROR_RESPONSE = {"error": "Could not score this project, please try again"}


@router.post("/projects/{project_id}/score")
async def score_project_by_id(project_id: str, current_user: dict = Depends(get_request_user)):
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
    project_id: str, payload: FindingReasonRequest, current_user: dict = Depends(get_request_user)
):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        findings = project.get("findings", [])
        finding_index, finding = _resolve_finding(findings, payload.finding_index, payload.finding_id)
        if finding is None:
            return JSONResponse(status_code=400, content={"error": "Invalid finding index"})

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
            finding_updates = {
                "reasoning": result.model_dump(),
                "knowledge_retrieval": {
                "mode": knowledge.get("mode"),
                "available": knowledge.get("available"),
                "record_count": len(knowledge.get("records", [])),
                "rule_ids": [r.get("rule_id") for r in knowledge.get("records", [])],
                },
                "related_files": [f["path"] for f in context["related_files"]],
            }
            if not await update_owned_finding(project_id, current_user["_id"], finding["finding_id"], finding_updates):
                findings[finding_index].update(finding_updates)
                await update_owned_project(project_id, current_user["_id"], {"findings": findings})
        except Exception as exc:
            print(f"[projects] failed to persist finding reasoning: {exc}")

        return result
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_REASON_ERROR_RESPONSE)


_TRANSFORM_ERROR_RESPONSE = {"error": "Could not generate a fix for this finding, please try again"}


def _deterministic_random_choice_fix(finding: dict, content: str) -> FindingTransform | None:
    """Recover a safe, exact patch when the model preview missed source formatting."""
    if finding.get("rule") != "insecure_random_secret" or content.count("random.choice(") != 1:
        return None
    if "import secrets" in content:
        fixed = content.replace("random.choice(", "secrets.choice(", 1)
    else:
        import_match = re.search(
            r"(?m)^(?P<imports>\s*import\s+[^\r\n#]*\brandom\b[^\r\n#]*)(?P<comment>\s*(?:#.*)?)$",
            content,
        )
        if import_match is None:
            return None
        imports = import_match.group("imports").rstrip()
        fixed = content[: import_match.start()] + f"{imports}, secrets{import_match.group('comment')}" + content[import_match.end() :]
        fixed = fixed.replace("random.choice(", "secrets.choice(", 1)
    return FindingTransform(
        original_snippet=content,
        proposed_fix=fixed,
        explanation="Replaced predictable random.choice with secrets.choice and added the standard-library secrets import.",
        confidence=0.96,
    )


def _enrich_transform(transform: FindingTransform, finding: dict, content: str | None = None) -> FindingTransform:
    original = transform.original_snippet or transform.original_code
    fixed = transform.proposed_fix or transform.fixed_code
    diff = make_unified_diff(original, fixed, finding.get("file") or "file") if original and fixed else ""
    can_apply = False
    metadata = {}
    if content is not None and original and fixed:
        metadata = build_patch_metadata(content, original, fixed, filename=finding.get("file") or "file")
        if metadata.get("apply_failure_reason") == "target_not_found":
            fallback = _deterministic_random_choice_fix(finding, content)
            if fallback is not None:
                transform = fallback
                original = fallback.original_snippet
                fixed = fallback.proposed_fix
                diff = make_unified_diff(original, fixed, finding.get("file") or "file")
                metadata = build_patch_metadata(content, original, fixed, filename=finding.get("file") or "file")
        can_apply = metadata["can_apply"]
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
    transform.apply_failure_reason = metadata.get("apply_failure_reason", "")
    transform.source_hash = metadata.get("source_hash", "")
    transform.target_start = metadata.get("target_start", 0)
    transform.target_end = metadata.get("target_end", 0)
    transform.start_line = metadata.get("start_line", 0)
    transform.end_line = metadata.get("end_line", 0)
    reason = transform.apply_failure_reason
    transform.validation = {
        "target_found": bool(original) and reason != "target_not_found",
        "target_unique": bool(original) and reason != "ambiguous_target",
        "source_unchanged": content is not None and reason != "stale_source",
        "patch_no_overlap": content is not None and reason != "overlapping_patch",
        "diff_validated": bool(transform.diff) and reason != "malformed_fix",
    }
    return transform


@router.post("/projects/{project_id}/findings/transform", response_model=FindingTransform)
async def transform_finding(
    project_id: str, payload: FindingReasonRequest, current_user: dict = Depends(get_request_user)
):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        if is_fix_all_running(project_id):
            return JSONResponse(status_code=409, content={"error": "Fix All is currently running for this project. Wait for it to finish before making manual changes."})

        findings = project.get("findings", [])
        finding_index, finding = _resolve_finding(findings, payload.finding_index, payload.finding_id)
        if finding is None:
            return JSONResponse(status_code=400, content={"error": "Invalid finding index"})

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
        result.finding_id = finding["finding_id"]
        result.document_type = "project"

        try:
            if not await update_owned_finding(
                project_id, current_user["_id"], finding["finding_id"], {"transform": result.model_dump()}
            ):
                findings[finding_index]["transform"] = result.model_dump()
                await update_owned_project(project_id, current_user["_id"], {"findings": findings})
        except Exception as exc:
            print(f"[projects] failed to persist finding transform: {exc}")

        return result
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_TRANSFORM_ERROR_RESPONSE)


_HACKER_LENS_ERROR_RESPONSE = {"error": "Hacker Mode analysis failed, please retry"}


@router.post("/projects/{project_id}/hacker-lens")
async def hacker_lens_report(project_id: str, current_user: dict = Depends(get_request_user)):
    # Independent adversarial AI review -- reuses the same stored project the
    # normal CODE MASTER AI pipeline already analyzed (one ZIP upload, one project_id).
    # Deliberately does NOT touch security_findings, RAG/knowledge retrieval,
    # or the deterministic analyzer -- failure here must never affect Normal
    # CODE MASTER AI, which is why this is its own try/except around its own call.
    stage_start = time.monotonic()
    print(f"[stage] HACKER_START project_id={project_id}")
    try:
        project = await get_owned_project_metadata(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        report = await run_hacker_lens(project)
        print(
            f"[stage] HACKER_COMPLETE project_id={project_id} hydrated_files={len(getattr(report, 'files_analyzed', []) or [])} "
            f"error={bool(getattr(report, 'error', ''))} duration_ms={round((time.monotonic() - stage_start) * 1000)}"
        )
        return report
    except Exception as exc:
        print(f"[projects] hacker-lens unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_HACKER_LENS_ERROR_RESPONSE)


_BRUTAL_AUDIT_ERROR_RESPONSE = {"error": "Brutal Audit failed, please retry"}


@router.post("/projects/{project_id}/brutal-audit")
async def brutal_audit_report(project_id: str, current_user: dict = Depends(get_request_user)):
    # Independent production-readiness review. Reuses the existing stored
    # project and does not touch normal findings, Hacker Mode, or RAG.
    stage_start = time.monotonic()
    print(f"[stage] BRUTAL_START project_id={project_id}")
    try:
        project = await get_owned_project_metadata(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        report = await run_brutal_audit(project)
        print(
            f"[stage] BRUTAL_COMPLETE project_id={project_id} hydrated_files={len(getattr(report, 'files_analyzed', []) or [])} "
            f"error={bool(getattr(report, 'error', ''))} duration_ms={round((time.monotonic() - stage_start) * 1000)}"
        )
        return report
    except Exception as exc:
        print(f"[projects] brutal-audit unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_BRUTAL_AUDIT_ERROR_RESPONSE)


_BLAST_RADIUS_ERROR_RESPONSE = {"error": "Blast Radius analysis failed, please retry"}


@router.get("/projects/{project_id}/blast-radius")
async def blast_radius_report(project_id: str, current_user: dict = Depends(get_request_user)):
    # Static Python dependency-impact analysis. It reuses the same stored
    # project_id, hydrates a bounded Python file selection inside the service,
    # and does not query RAG or modify normal findings.
    stage_start = time.monotonic()
    print(f"[stage] BLAST_RADIUS_START project_id={project_id}")
    try:
        project = await get_owned_project_metadata(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})

        report = await build_blast_radius(project)
        print(
            f"[stage] BLAST_RADIUS_COMPLETE project_id={project_id} components={report.get('summary', {}).get('components_analyzed', 0)} "
            f"edges={len(report.get('edges', []))} ai_error={bool(report.get('ai', {}).get('error'))} "
            f"duration_ms={round((time.monotonic() - stage_start) * 1000)}"
        )
        return report
    except Exception as exc:
        print(f"[projects] blast-radius unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_BLAST_RADIUS_ERROR_RESPONSE)


_AUTOMATION_ERROR_RESPONSE = {"error": "Could not start automation, please retry"}


# V2_AUTOMATION_DISABLED:
# Automation is intentionally excluded from CODE MASTER AI V1.
# Preserve this code for the V2 automation workflow.
# @router.post("/projects/{project_id}/automation")
async def start_project_automation(project_id: str, current_user: dict = Depends(get_request_user)):
    from services.automation import start_automation

    try:
        state = await start_automation(project_id, current_user["_id"])
        return JSONResponse(status_code=202, content=state)
    except LookupError:
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    except RuntimeError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})
    except Exception as exc:
        print(f"[projects] automation start error: {exc}")
        return JSONResponse(status_code=500, content=_AUTOMATION_ERROR_RESPONSE)


# V2_AUTOMATION_DISABLED:
# Automation is intentionally excluded from CODE MASTER AI V1.
# Preserve this code for the V2 automation workflow.
# @router.get("/projects/{project_id}/automation/status")
async def project_automation_status(project_id: str, current_user: dict = Depends(get_request_user)):
    from services.automation import get_automation_status

    project = await get_owned_project_metadata(project_id, current_user["_id"])
    if project is None:
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    state = await get_automation_status(project_id, current_user["_id"])
    if state is None:
        return JSONResponse(status_code=404, content={"error": "No automation run found for this project"})
    return state


# V2_AUTOMATION_DISABLED:
# Automation is intentionally excluded from CODE MASTER AI V1.
# Preserve this code for the V2 automation workflow.
# @router.post("/projects/{project_id}/automation/stop")
async def stop_project_automation(project_id: str, current_user: dict = Depends(get_request_user)):
    from services.automation import request_stop as request_automation_stop

    project = await get_owned_project_metadata(project_id, current_user["_id"])
    if project is None:
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    return {"stopped": request_automation_stop(project_id)}


_COMMIT_GUARD_ERROR_RESPONSE = {"error": "Could not start Commit Guard, please retry"}


@router.post("/projects/{project_id}/commit-guard")
async def start_commit_guard_endpoint(project_id: str, current_user: dict = Depends(get_request_user)):
    # Read-only: never applies a patch, never touches source, never calls
    # Fix All. Ownership + existence checked the same way every other
    # project-scoped endpoint here does.
    try:
        project = await get_owned_project_metadata(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        state = await start_commit_guard(project_id, current_user["_id"])
        return JSONResponse(status_code=202, content={"job_id": state["job_id"], "status": state["status"]})
    except Exception as exc:
        print(f"[projects] commit-guard start error: {exc}")
        return JSONResponse(status_code=500, content=_COMMIT_GUARD_ERROR_RESPONSE)


@router.get("/projects/{project_id}/commit-guard/status")
async def commit_guard_status_endpoint(project_id: str, current_user: dict = Depends(get_request_user)):
    project = await get_owned_project_metadata(project_id, current_user["_id"])
    if project is None:
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    state = await get_commit_guard_status(project_id, current_user["_id"])
    if state is None:
        return JSONResponse(status_code=404, content={"error": "No Commit Guard run found for this project"})
    return state


_PR_GUARD_ERROR_RESPONSE = {"error": "Could not start PR Guard, please retry"}


@router.post("/projects/{project_id}/pr-guard")
async def start_pr_guard_endpoint(
    project_id: str,
    payload: PRGuardRequest,
    current_user: dict = Depends(get_request_user),
):
    try:
        project = await get_owned_project_metadata(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        if not project.get("github_owner") or not project.get("github_repo"):
            return JSONResponse(status_code=400, content={"error": "PR Guard requires a GitHub-backed project."})
        state = await start_pr_guard(project_id, current_user["_id"], payload.pull_request_number)
        return JSONResponse(status_code=202, content=state)
    except Exception as exc:
        print(f"[projects] pr-guard start error: {exc}")
        return JSONResponse(status_code=500, content=_PR_GUARD_ERROR_RESPONSE)


@router.get("/projects/{project_id}/pr-guard/{run_id}/status")
async def pr_guard_status_endpoint(project_id: str, run_id: str, current_user: dict = Depends(get_request_user)):
    project = await get_owned_project_metadata(project_id, current_user["_id"])
    if project is None:
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    state = await get_pr_guard_status(project_id, current_user["_id"], run_id)
    if state is None:
        return JSONResponse(status_code=404, content={"error": "No PR Guard run found for this project"})
    return state


@router.get("/projects/{project_id}/pr-guard/status")
async def latest_pr_guard_status_endpoint(
    project_id: str,
    pull_request_number: int,
    current_user: dict = Depends(get_request_user),
):
    project = await get_owned_project_metadata(project_id, current_user["_id"])
    if project is None:
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    state = await get_pr_guard_status(project_id, current_user["_id"], pr_number=pull_request_number)
    if state is None:
        return JSONResponse(status_code=404, content={"error": "No PR Guard run found for this project"})
    return state


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
    project_id: str, payload: FindingReasonRequest | None = None, current_user: dict = Depends(get_request_user)
):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        # V2_AUTOMATION_DISABLED:
        # Automation is intentionally excluded from CODE MASTER AI V1.
        # Preserve this code for the V2 automation workflow.
        # if is_automation_running(project_id):
        #     return JSONResponse(status_code=409, content={"error": "Automation is currently running for this project. Wait for it to finish before reanalyzing manually."})
        job, created = await enqueue_analysis(
            project_id,
            current_user["_id"],
            lambda _job_id: _run_project_analysis(project_id, current_user["_id"]),
        )
        return JSONResponse(status_code=202, content={"job_id": job["_id"], "status": job.get("status", "queued"), "created": created})
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_REANALYZE_ERROR_RESPONSE)


_APPLY_ERROR_RESPONSE = {"error": "Could not apply this fix safely"}
_DOWNLOAD_ERROR_RESPONSE = {"error": "Could not create fixed ZIP"}


async def _stream_spooled_file(spool):
    """Yield bounded chunks and close the temporary archive after the response."""
    try:
        while True:
            chunk = await asyncio.to_thread(spool.read, 1024 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        spool.close()


@router.post("/projects/{project_id}/fixes/apply")
async def apply_project_fix(
    project_id: str, payload: ApplyProjectFixRequest, current_user: dict = Depends(get_request_user)
):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        # V2_AUTOMATION_DISABLED:
        # Automation is intentionally excluded from CODE MASTER AI V1.
        # Preserve this code for the V2 automation workflow.
        # if is_automation_running(project_id):
        #     return JSONResponse(status_code=409, content={"error": "Automation is currently running for this project. Wait for it to finish before applying manual fixes."})
        if is_fix_all_running(project_id):
            return JSONResponse(status_code=409, content={"error": "Fix All is currently running for this project. Wait for it to finish before making manual changes."})
        findings = project.get("findings", [])
        finding_index, finding = _resolve_finding(findings, payload.finding_index, payload.finding_id)
        if finding is None:
            return JSONResponse(status_code=400, content={"error": "Invalid finding index"})
        transform = finding.get("transform") or {}
        original = transform.get("original_snippet") or transform.get("original_code") or ""
        fixed = transform.get("proposed_fix") or transform.get("fixed_code") or ""
        if not original or not fixed:
            return JSONResponse(status_code=400, content={"error": "Generate a fix before applying it"})

        file_entry = next((f for f in project.get("files", []) if f.get("path") == finding.get("file")), None)
        if not file_entry or file_entry.get("content") is None:
            return JSONResponse(status_code=400, content={"error": "Could not locate target file content"})

        try:
            applied = apply_structured_patch(
                file_entry["content"],
                original,
                fixed,
                expected_hash=transform.get("source_hash") or None,
            )
        except PatchError as exc:
            finding["fix_state"] = "Conflict"
            await update_owned_project(project_id, current_user["_id"], {"findings": findings})
            print(
                f"[projects] apply fix rejected project_id={project_id} "
                f"finding_id={finding.get('finding_id')} reason={exc.reason}"
            )
            return JSONResponse(
                status_code=409,
                content={**_APPLY_ERROR_RESPONSE, "apply_failure_reason": exc.reason},
            )

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
                "finding_id": finding["finding_id"],
                "rule_id": finding.get("rule"),
                "file": finding.get("file"),
                "diff": applied.diff,
                "state": "Applied",
            }
        )

        updated = await update_owned_project(
            project_id,
            current_user["_id"],
            {
                "files": project["files"],
                "findings": findings,
                "patches": project.get("patches", []),
                "source_revision": int(project.get("source_revision", 1)) + 1,
                "analysis_status": "stale",
                "compliance_score": None,
            },
            expected_source_revision=int(project.get("source_revision", 1)),
        )
        if updated is False:
            return JSONResponse(
                status_code=409,
                content={"error": "Project source changed while this fix was being applied. Refresh and generate a new fix."},
            )
        print(f"[projects] fix applied user_id={current_user['_id']} project_id={project_id}")
        return {
            "status": "applied",
            "file": finding.get("file"),
            "modified_files": sorted({p.get("file") for p in project.get("patches", []) if p.get("file")}),
            "analysis_status": "stale",
            "verification": "Source updated. Run reanalysis to produce current findings and score.",
        }
    except Exception as exc:
        print(f"[projects] apply fix error: {exc}")
        return JSONResponse(status_code=500, content=_APPLY_ERROR_RESPONSE)


_FIX_ALL_ERROR_RESPONSE = {"error": "Could not start Fix All, please try again"}


@router.post("/projects/{project_id}/fix-all")
async def start_fix_all_endpoint(project_id: str, current_user: dict = Depends(get_request_user)):
    try:
        project = await get_owned_project_metadata(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        # V2_AUTOMATION_DISABLED:
        # Automation is intentionally excluded from CODE MASTER AI V1.
        # Preserve this code for the V2 automation workflow.
        # if is_automation_running(project_id):
        #     return JSONResponse(status_code=409, content={"error": "Automation is currently running for this project. Fix All is already controlled by the automation workflow."})
        if is_fix_all_running(project_id):
            existing = get_fix_all_status(project_id)
            return JSONResponse(
                status_code=202,
                content={"job_id": existing["job_id"], "status": existing["status"], "total": existing["total"]},
            )
        security_findings = project.get("security_findings", [])
        if not security_findings:
            return JSONResponse(status_code=400, content={"error": "No confirmed security findings to fix."})
        if project.get("analysis_status") == "stale":
            return JSONResponse(
                status_code=409,
                content={"error": "Repository changed after the last analysis. Re-analyze before running Fix All."},
            )
        state = await start_fix_all(project_id, current_user["_id"])
        return JSONResponse(
            status_code=202,
            content={"job_id": state["job_id"], "status": state["status"], "total": state["total"]},
        )
    except Exception as exc:
        print(f"[projects] fix-all start error: {exc}")
        return JSONResponse(status_code=500, content=_FIX_ALL_ERROR_RESPONSE)


@router.get("/projects/{project_id}/fix-all/status")
async def fix_all_status(project_id: str, current_user: dict = Depends(get_request_user)):
    project = await get_owned_project_metadata(project_id, current_user["_id"])
    if project is None:
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    # Recovery-aware: falls back to the Mongo-persisted run doc (and
    # corrects it to "failed") when this process has no in-memory record of
    # the run, e.g. it was started before a crash/restart -- see
    # services.fix_all.get_fix_all_status_with_recovery.
    state = await get_fix_all_status_with_recovery(project_id, current_user["_id"])
    if state is None:
        return JSONResponse(status_code=404, content={"error": "No Fix All run found for this project"})
    return {
        "job_id": state["job_id"],
        "status": state["status"],
        "total": state["total"],
        "processed": state["processed"],
        "results": state["results"],
        "report": state.get("report"),
        "error": state.get("error"),
    }


@router.post("/projects/{project_id}/fix-all/stop")
async def stop_fix_all_endpoint(project_id: str, current_user: dict = Depends(get_request_user)):
    project = await get_owned_project_metadata(project_id, current_user["_id"])
    if project is None:
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    stopped = request_stop(project_id)
    return {"stopped": stopped}


@router.get("/projects/{project_id}/download-fixed")
async def download_fixed_project(
    project_id: str, filename: str | None = None, current_user: dict = Depends(get_request_user)
):
    try:
        project = await get_owned_project(project_id, current_user["_id"])
        if project is None:
            return JSONResponse(status_code=404, content={"error": "Project not found"})
        # Spool to disk once the archive grows beyond a small in-memory buffer
        # instead of duplicating the complete ZIP with BytesIO.getvalue().
        buffer = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_entry in project.get("files", []):
                path = safe_archive_path(file_entry.get("path", ""))
                first = PurePosixPath(path).parts[0] if PurePosixPath(path).parts else ""
                if first in IGNORE_DIRS or path.endswith((".env", ".pyc")):
                    continue
                content = file_entry.get("content")
                if content is not None:
                    zf.writestr(path, content)
                elif file_entry.get("binary_ref"):
                    zf.writestr(path, await fetch_binary_content(file_entry["binary_ref"]))
        buffer.seek(0)
        print(f"[projects] download user_id={current_user['_id']} project_id={project_id}")
        project_name = project.get("project", {}).get("name") or "project"
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", filename or f"{project_name}-code-master-ai-fixed.zip").strip("-")
        if not safe_name.endswith(".zip"):
            safe_name += ".zip"
        return StreamingResponse(
            _stream_spooled_file(buffer),
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
async def chat_about_project(project_id: str, payload: ChatRequest, current_user: dict = Depends(get_request_user)):
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
        if knowledge or semantic_context:
            print(
                f"[projects] chat retrieval project_id={project_id} "
                f"knowledge_records={len((knowledge or {}).get('records', []))} "
                f"semantic_projects={len(semantic_context)}"
            )

        return {
            **result,
            "retrieved_files": [f["path"] for f in retrieved],
        }
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_CHAT_ERROR_RESPONSE)
