from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.self_healing import analyze_runtime_events, get_execution, get_history, run_workflow

router = APIRouter()


class WorkflowRequest(BaseModel):
    scenario: str = Field(default="schema_mismatch", pattern="^(schema_mismatch|invalid_credentials)$")


class RuntimeEvent(BaseModel):
    step: str = Field(min_length=1, max_length=120)
    status: str = Field(default="complete", max_length=40)
    message: str | None = Field(default=None, max_length=2000)
    error: str | None = Field(default=None, max_length=2000)
    error_type: str | None = Field(default=None, max_length=120)
    http_status: int | None = Field(default=None, ge=100, le=599)
    payload: dict | None = None


class RuntimeMonitorRequest(BaseModel):
    workflow_name: str = Field(min_length=1, max_length=100)
    events: list[RuntimeEvent] = Field(min_length=1, max_length=30)


@router.post("/workflows/run")
async def run(payload: WorkflowRequest):
    try:
        return await run_workflow(payload.scenario)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflows/monitor")
async def monitor(payload: RuntimeMonitorRequest):
    try:
        return await analyze_runtime_events(payload.workflow_name, [event.model_dump(exclude_none=True) for event in payload.events])
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.get("/workflows/history")
async def history():
    return {"items": get_history(), "persistence": "process_memory_only"}


@router.get("/workflows/{execution_id}")
async def execution(execution_id: str):
    item = get_execution(execution_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return item
