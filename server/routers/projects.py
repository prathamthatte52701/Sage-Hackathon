import os
import zipfile
from io import BytesIO
from pathlib import PurePosixPath

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from db.mongo import get_project, save_project, update_project
from services.analyzer import SOURCE_LANGUAGES, analyze_project

router = APIRouter()

MAX_ZIP_SIZE = 20 * 1024 * 1024  # 20MB
MAX_FILE_COUNT = 500
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


@router.post("/projects/upload")
async def upload_project(file: UploadFile = File(...), session_id: str = Form(...)):
    try:
        raw_bytes = await file.read()

        if len(raw_bytes) > MAX_ZIP_SIZE:
            return JSONResponse(status_code=400, content={"error": "ZIP file exceeds the 20MB limit"})

        buffer = BytesIO(raw_bytes)
        if not zipfile.is_zipfile(buffer):
            return JSONResponse(status_code=400, content={"error": "Uploaded file is not a valid ZIP archive"})

        with zipfile.ZipFile(buffer) as zf:
            names = zf.namelist()

            if len(names) > MAX_FILE_COUNT:
                return JSONResponse(
                    status_code=400, content={"error": "ZIP contains too many files (max 500)"}
                )

            if any(_is_unsafe_path(name) for name in names):
                return JSONResponse(status_code=400, content={"error": "ZIP contains unsafe file paths"})

            files_index = []
            ignored_counts: dict[str, int] = {}

            for name in names:
                if name.endswith("/"):
                    continue  # directory entry

                if _is_ignored(name):
                    top_ignored = next(
                        part for part in PurePosixPath(name.replace("\\", "/")).parts if part in IGNORE_DIRS
                    )
                    ignored_counts[top_ignored] = ignored_counts.get(top_ignored, 0) + 1
                    continue

                info = zf.getinfo(name)
                language = _guess_language(name)

                content = None
                if language in SOURCE_LANGUAGES:
                    text = zf.read(name).decode("utf-8", errors="replace")
                    if len(text) < MAX_CONTENT_SIZE:
                        content = text

                files_index.append(
                    {"path": name, "language": language, "size": info.file_size, "content": content}
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
                "name": _derive_project_name(file.filename),
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

        project_id = await save_project(project_representation, session_id)

        return {"project_id": project_id, "project": project_representation, "warnings": warnings}
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_ERROR_RESPONSE)


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
