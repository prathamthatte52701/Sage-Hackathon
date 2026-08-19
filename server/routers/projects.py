import copy
import json
import os
import re
import zipfile
from io import BytesIO
from pathlib import PurePosixPath

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from db.mongo import get_project, save_project, update_project
from models.schemas import FindingReasonRequest, FindingReasoning, FindingTransform
from services.analyzer import SOURCE_LANGUAGES, analyze_project
from services.groq_client import GroqUnavailableError, call_groq
from services.prompt_builder import build_finding_reasoning_prompt, build_transform_prompt
from services.scoring import FINDING_CATEGORY_MAP, RULE_TO_STANDARD, compute_score
from services.standards import get_standard_by_id, get_standards_for

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


def _extract_json(raw_text: str):
    """Try direct json.loads, then fall back to extracting {...} substring."""
    try:
        return json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        pass

    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


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


def _build_finding_reasoning(raw: dict) -> FindingReasoning:
    """Coerce/drop bad-typed fields instead of crashing, same pattern as _build_issue."""
    data = dict(raw) if isinstance(raw, dict) else {}

    if not isinstance(data.get("findingConfirmed"), bool):
        data.pop("findingConfirmed", None)

    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        data.pop("confidence", None)

    for field in ("severity", "reasoning", "impact", "recommendation", "suggestedFix"):
        if field in data and not isinstance(data[field], str):
            data.pop(field, None)

    if data.get("severity") not in ("critical", "high", "medium", "low"):
        data.pop("severity", None)

    return FindingReasoning(**{k: v for k, v in data.items() if k in FindingReasoning.model_fields})


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

        prompt = build_finding_reasoning_prompt(finding, code_snippet, language, matched_standards)
        messages = [{"role": "user", "content": prompt}]

        result = FindingReasoning()
        try:
            raw = await call_groq(messages)
            parsed = _extract_json(raw)

            if parsed is None:
                retry_messages = [
                    {
                        "role": "user",
                        "content": prompt
                        + "\n\nYour previous response was not valid JSON. Respond with ONLY the JSON object, nothing else.",
                    }
                ]
                raw = await call_groq(retry_messages)
                parsed = _extract_json(raw)

            if parsed is not None:
                result = _build_finding_reasoning(parsed)
                result.citedStandards = [
                    {"id": s["id"], "title": s["title"], "evidenceSource": s["evidenceSource"]}
                    for s in matched_standards
                ]
        except GroqUnavailableError:
            result = FindingReasoning()

        try:
            findings[payload.finding_index]["reasoning"] = result.model_dump()
            await update_project(project_id, {"findings": findings})
        except Exception as exc:
            print(f"[projects] failed to persist finding reasoning: {exc}")

        return result
    except Exception as exc:
        print(f"[projects] unhandled error: {exc}")
        return JSONResponse(status_code=500, content=_REASON_ERROR_RESPONSE)


def _build_finding_transform(raw: dict) -> FindingTransform:
    """Coerce/drop bad-typed fields instead of crashing, same pattern as _build_finding_reasoning."""
    data = dict(raw) if isinstance(raw, dict) else {}

    for field in ("original_snippet", "proposed_fix", "explanation"):
        if field in data and not isinstance(data[field], str):
            data.pop(field, None)

    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        data.pop("confidence", None)

    return FindingTransform(**{k: v for k, v in data.items() if k in FindingTransform.model_fields})


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

        prompt = build_transform_prompt(finding, code_snippet, language, matched_standards)
        messages = [{"role": "user", "content": prompt}]

        result = FindingTransform()
        try:
            raw = await call_groq(messages)
            parsed = _extract_json(raw)

            if parsed is None:
                retry_messages = [
                    {
                        "role": "user",
                        "content": prompt
                        + "\n\nYour previous response was not valid JSON. Respond with ONLY the JSON object, nothing else.",
                    }
                ]
                raw = await call_groq(retry_messages)
                parsed = _extract_json(raw)

            if parsed is not None:
                result = _build_finding_transform(parsed)
        except GroqUnavailableError:
            result = FindingTransform()

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
