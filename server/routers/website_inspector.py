from copy import deepcopy
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import MONGO_URL
from db.mongo import get_db, get_owned_project
from services.auth import get_request_user
from services.website_inspector import InspectionError, diagnose_deployment_logs, inspect_website

router = APIRouter()
_history: dict[str, list[dict]] = {}


class InspectRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    logs: str | None = Field(default=None, max_length=20_000)
    source_project_id: str | None = Field(default=None, max_length=100)


def _match_source_files(logs: str, files: list[dict]) -> list[dict]:
    references = []
    patterns = [re.compile(r"File [\"']([^\"']+)[\"'], line (\d+)"), re.compile(r"(?:at\s+.*?\()?([A-Za-z0-9_./\\-]+\.[cm]?[jt]sx?):(\d+)(?::\d+)?\)?")]
    for pattern in patterns:
        references.extend((path.replace("\\", "/").lstrip("./"), int(line)) for path, line in pattern.findall(logs))
    matches = []
    for reference, line in references:
        for file_entry in files:
            path = str(file_entry.get("path", "")).replace("\\", "/").lstrip("./")
            if path and (reference == path or reference.endswith("/" + path)):
                matches.append({"path": path, "line": line, "evidence": f"Stack trace references {reference}:{line}"})
                break
        if len(matches) >= 10:
            break
    return matches


@router.post("/website-inspector/inspect")
async def inspect(payload: InspectRequest, user: dict = Depends(get_request_user)):
    try:
        result = await inspect_website(payload.url)
    except InspectionError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc), "inspection_trace": [{"stage": exc.stage, "status": "failed", "message": str(exc)}]})
    except Exception as exc:
        print(f"[website-inspector] inspection failed: {type(exc).__name__}")
        raise HTTPException(status_code=502, detail="Website inspection failed. Check the URL and try again.") from exc
    if payload.logs:
        from services.website_inspector import _safe_log_text
        safe_logs = _safe_log_text(payload.logs)
        result["log_diagnosis"] = await diagnose_deployment_logs(payload.logs)
        if payload.source_project_id:
            if not MONGO_URL:
                raise HTTPException(status_code=503, detail="Source-project matching requires the configured project database. Log diagnosis remains available without it.")
            project = await get_owned_project(payload.source_project_id, str(user.get("_id", "demo-user")))
            if project is None:
                raise HTTPException(status_code=404, detail="Connected source project was not found for this account.")
            result["source_matches"] = _match_source_files(safe_logs, project.get("files", []))
            result["source_mapping"] = "matched" if result["source_matches"] else "no_stack_frame_match"
            if not result["source_matches"]:
                result["source_mapping_note"] = "Logs did not contain a stack-frame file path that matches the uploaded source. Diagnosis remains log-based."
    elif payload.source_project_id:
        raise HTTPException(status_code=400, detail="Add deployment logs to map them to the selected source project.")
    result["inspection_id"] = __import__("uuid").uuid4().hex
    result["persistence"] = "in_memory"
    owner_id = str(user.get("_id", "demo-user"))
    stored_result = deepcopy(result)
    if stored_result.get("log_diagnosis"):
        stored_result["log_diagnosis"].pop("redacted_log_excerpt", None)
    _history.setdefault(owner_id, []).insert(0, stored_result)
    del _history[owner_id][20:]
    if MONGO_URL:
        try:
            stored_result["persistence"] = "mongodb"
            await get_db().website_inspections.insert_one({**deepcopy(stored_result), "owner_user_id": owner_id})
            result["persistence"] = "mongodb"
            _history[owner_id][0]["persistence"] = "mongodb"
        except Exception as exc:
            print(f"[website-inspector] history persistence unavailable: {type(exc).__name__}")
            result["persistence"] = "in_memory_fallback"
            _history[owner_id][0]["persistence"] = "in_memory_fallback"
    return result


@router.get("/website-inspector/history")
async def history(user: dict = Depends(get_request_user)):
    owner_id = str(user.get("_id", "demo-user"))
    items = deepcopy(_history.get(owner_id, []))
    persistence = "in_memory"
    if MONGO_URL:
        try:
            cursor = get_db().website_inspections.find({"owner_user_id": owner_id}, {"_id": 0, "owner_user_id": 0}).sort("inspected_at", -1).limit(20)
            stored = [item async for item in cursor]
            return {"items": stored, "persistence": "mongodb"}
        except Exception as exc:
            print(f"[website-inspector] history lookup unavailable: {type(exc).__name__}")
            persistence = "in_memory_fallback"
    return {"items": items, "persistence": persistence}
