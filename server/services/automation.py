"""Automated hardening workflow orchestration for CODE MASTER AI.

This module deliberately does not implement scanning, fixing, Hacker Mode,
Brutal Audit, or Blast Radius logic. It coordinates the existing services and
keeps a small server-side run state so refreshes can recover the current stage.
"""

# V2_AUTOMATION_DISABLED:
# Automation is intentionally excluded from CODE MASTER AI V1.
# Preserve this code for the V2 automation workflow.

import asyncio
import copy
import time
from datetime import datetime, timezone

from db.mongo import (
    create_automation_run,
    get_owned_automation_run,
    get_owned_project_metadata,
    update_automation_run,
)
from services.blast_radius import build_blast_radius
from services.brutal_audit import run_brutal_audit
from services.fix_all import get_fix_all_status_with_recovery, is_fix_all_running, start_fix_all
from services.hacker_lens import run_hacker_lens

MAX_AUTO_FIX_CYCLES = 3
TERMINAL_STATUSES = {"complete", "paused", "failed", "stopped"}
RUNNING_STATUSES = {"queued", "running"}

_active_runs: dict[str, dict] = {}
_guard = asyncio.Lock()
_counter = 0


def is_automation_running(project_id: str) -> bool:
    state = _active_runs.get(project_id)
    return bool(state and state.get("status") in RUNNING_STATUSES)


def request_stop(project_id: str) -> bool:
    state = _active_runs.get(project_id)
    if not state or state.get("status") not in RUNNING_STATUSES:
        return False
    state["stop_requested"] = True
    state["message"] = "Automation will stop at the next safe stage boundary."
    return True


def _stage(status: str = "pending", **extra) -> dict:
    return {"status": status, "error": None, **extra}


def _new_state(project_id: str, owner_user_id: str, job_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "job_id": job_id,
        "run_id": None,
        "project_id": project_id,
        "owner_user_id": owner_user_id,
        "status": "running",
        "current_stage": "defender",
        "stop_requested": False,
        "started_at": now,
        "updated_at": now,
        "message": "Repository loaded. Defender analysis is starting.",
        "defender": _stage("running", initial_findings=0, remaining_findings=0, fixed=0, failed=0, fix_cycles=0),
        "fix_cycles": [],
        "hacker": _stage(),
        "brutal": _stage(),
        "blast_radius": _stage(),
        "final_report": None,
        "download": {"ready": False, "source_revision": None, "analysis_revision": None, "fresh": False},
    }


def _public_state(state: dict) -> dict:
    public = copy.deepcopy(state)
    public.pop("owner_user_id", None)
    public.pop("stop_requested", None)
    return _jsonable(public)


def _jsonable(value):
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    return value


async def _persist(state: dict, updates: dict | None = None) -> None:
    if updates:
        state.update(updates)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    run_id = state.get("run_id")
    if not run_id:
        return
    try:
        await update_automation_run(run_id, state["owner_user_id"], _public_state(state))
    except Exception as exc:
        print(f"[automation] persistence update failed project_id={state.get('project_id')}: {type(exc).__name__}: {exc}")


async def _create_persisted_run(state: dict) -> None:
    try:
        run_id = await create_automation_run(state["project_id"], state["owner_user_id"], _public_state(state))
        state["run_id"] = run_id
        await _persist(state)
    except Exception as exc:
        print(f"[automation] persistence unavailable, continuing in-memory only: {type(exc).__name__}: {exc}")


async def get_automation_status(project_id: str, owner_user_id: str) -> dict | None:
    live = _active_runs.get(project_id)
    if live is not None:
        return _public_state(live)
    try:
        run = await get_owned_automation_run(project_id, owner_user_id)
    except Exception as exc:
        print(f"[automation] persisted status lookup failed project_id={project_id}: {type(exc).__name__}: {exc}")
        return None
    if not run:
        return None
    run.pop("_id", None)
    run.pop("owner_user_id", None)
    if run.get("status") in RUNNING_STATUSES:
        run["status"] = "failed"
        run["message"] = "Automation was interrupted because the server restarted. Start a new automation run to continue."
        for stage_name in ("defender", "hacker", "brutal", "blast_radius"):
            stage = run.get(stage_name)
            if isinstance(stage, dict) and stage.get("status") == "running":
                stage["status"] = "failed"
                stage["error"] = "interrupted"
    return run


async def start_automation(project_id: str, owner_user_id: str) -> dict:
    global _counter
    project = await get_owned_project_metadata(project_id, owner_user_id)
    if project is None:
        raise LookupError("Project not found")

    async with _guard:
        existing = _active_runs.get(project_id)
        if existing and existing.get("status") in RUNNING_STATUSES:
            return _public_state(existing)
        if is_fix_all_running(project_id):
            raise RuntimeError("Fix All is already running for this project.")

        _counter += 1
        state = _new_state(project_id, owner_user_id, f"automation-{project_id}-{_counter}")
        _active_runs[project_id] = state

    await _create_persisted_run(state)
    asyncio.create_task(_run_automation(project_id, owner_user_id, state), name=f"automation:{project_id}")
    return _public_state(state)


async def _run_defender(project_id: str, owner_user_id: str, state: dict) -> None:
    from routers.projects import _run_project_analysis  # lazy import avoids router/service cycle

    state["current_stage"] = "defender"
    state["defender"]["status"] = "running"
    state["message"] = "Defender is analyzing confirmed security findings."
    await _persist(state)

    analysis = await _run_project_analysis(project_id, owner_user_id)
    if analysis.get("stale"):
        state["defender"]["status"] = "paused"
        state["defender"]["error"] = "Project source changed during Defender analysis."
        await _persist(state)
        raise RuntimeError("Project source changed during Defender analysis; rerun automation on the latest revision.")
    project = await get_owned_project_metadata(project_id, owner_user_id)
    if project is None:
        raise LookupError("Project not found")

    initial = len(project.get("security_findings") or project.get("findings") or [])
    state["defender"].update({"initial_findings": initial, "remaining_findings": initial})
    await _persist(state)

    for cycle in range(1, MAX_AUTO_FIX_CYCLES + 1):
        if state.get("stop_requested"):
            state["status"] = "stopped"
            state["message"] = "Automation stopped before the next fix cycle."
            await _persist(state)
            return
        project = await get_owned_project_metadata(project_id, owner_user_id)
        remaining = len(project.get("security_findings") or project.get("findings") or []) if project else 0
        source_revision_before = project.get("source_revision") if project else None
        analysis_revision_before = project.get("analysis_revision") if project else None
        signature_before = _finding_signature(project)
        state["defender"]["remaining_findings"] = remaining
        if remaining == 0:
            break

        state["defender"]["fix_cycles"] = cycle
        state["message"] = f"Auto Fix Loop cycle {cycle}/{MAX_AUTO_FIX_CYCLES} is patching confirmed findings."
        await _persist(state)
        fix_state = await start_fix_all(project_id, owner_user_id)
        fix_state = await _wait_for_fix_all(project_id, owner_user_id, fix_state, state)
        report = fix_state.get("report") or {}
        state["defender"]["fixed"] = state["defender"].get("fixed", 0) + int(report.get("fixed", 0) or 0)
        state["defender"]["failed"] = state["defender"].get("failed", 0) + int(report.get("failed", 0) or 0)
        project = await get_owned_project_metadata(project_id, owner_user_id)
        findings_after = len(project.get("security_findings") or project.get("findings") or []) if project else remaining
        source_revision_after = project.get("source_revision") if project else None
        analysis_revision_after = project.get("analysis_revision") if project else None
        signature_after = _finding_signature(project)
        attempted = int(report.get("attempted", 0) or report.get("total", 0) or remaining)
        fixed = int(report.get("fixed", 0) or 0)
        failed = int(report.get("failed", 0) or 0)
        skipped = int(report.get("skipped", 0) or max(0, attempted - fixed - failed))
        cycle_record = {
            "cycle_number": cycle,
            "findings_before": remaining,
            "attempted": attempted,
            "fixed": fixed,
            "failed": failed,
            "skipped": skipped,
            "findings_after": findings_after,
            "source_revision_before": source_revision_before,
            "source_revision_after": source_revision_after,
            "analysis_revision_before": analysis_revision_before,
            "analysis_revision_after": analysis_revision_after,
            "status": "complete",
        }
        no_progress = (
            findings_after == remaining
            and signature_after == signature_before
            and source_revision_after == source_revision_before
        )
        if no_progress:
            cycle_record["status"] = "no_progress"
            state["defender"]["no_progress"] = True
            state["message"] = "Auto Fix Loop stopped because the remaining confirmed findings did not change."
        state.setdefault("fix_cycles", []).append(cycle_record)
        state["defender"]["cycle_history"] = state["fix_cycles"]
        state["defender"]["remaining_findings"] = findings_after
        await _persist(state)
        if no_progress:
            break

    if state.get("status") == "stopped":
        return
    remaining = state["defender"].get("remaining_findings", 0)
    state["defender"]["status"] = "complete"
    state["defender"]["manual_review_required"] = remaining > 0
    state["message"] = "Defender complete." if remaining == 0 else "Defender completed with issues requiring manual review."
    await _persist(state)


def _finding_signature(project: dict | None) -> list[tuple]:
    if not project:
        return []
    findings = project.get("security_findings") or project.get("findings") or []
    signature = []
    for finding in findings:
        signature.append(
            (
                finding.get("stable_id") or finding.get("id") or finding.get("rule_id") or finding.get("rule"),
                finding.get("file") or finding.get("path"),
                finding.get("line"),
                finding.get("evidence"),
                finding.get("severity"),
            )
        )
    return sorted(signature)


async def _wait_for_fix_all(project_id: str, owner_user_id: str, fix_state: dict, state: dict) -> dict:
    latest = fix_state
    while latest.get("status") == "running":
        state["defender"]["fix_all"] = {
            "status": latest.get("status"),
            "processed": latest.get("processed", 0),
            "total": latest.get("total", 0),
        }
        await _persist(state)
        await asyncio.sleep(1)
        latest = await get_fix_all_status_with_recovery(project_id, owner_user_id) or latest
    if latest.get("status") != "completed":
        state["defender"]["status"] = "paused"
        state["defender"]["error"] = latest.get("error") or "Fix All did not complete safely."
        raise RuntimeError(state["defender"]["error"])
    report = latest.get("report") or {}
    if report.get("status") == "completed_verification_failed":
        state["defender"]["status"] = "paused"
        state["defender"]["error"] = report.get("verification_note") or "Fix All completed without final verification."
        raise RuntimeError(state["defender"]["error"])
    return latest


async def _run_read_only_stage(state: dict, name: str, label: str, work):
    if state.get("stop_requested"):
        state["status"] = "stopped"
        state["message"] = f"Automation stopped before {label}."
        await _persist(state)
        return None
    state["current_stage"] = name
    state[name]["status"] = "running"
    state["message"] = f"{label} is running."
    await _persist(state)
    try:
        result = await work()
        state[name].update(_summarize_stage(name, result))
        state[name]["status"] = "complete"
        state[name]["result"] = result
        state["message"] = f"{label} complete."
        await _persist(state)
        return result
    except Exception as exc:
        state[name]["status"] = "failed"
        state[name]["continue_after_failure"] = True
        state[name]["error"] = f"{type(exc).__name__}: {exc}"
        state["message"] = f"{label} unavailable. Automation will continue."
        await _persist(state)
        return None


def _summarize_stage(name: str, result) -> dict:
    def field(key: str, default=None):
        if isinstance(result, dict):
            return result.get(key, default)
        return getattr(result, key, default)

    if name == "hacker":
        return {
            "attack_surfaces": len(field("attack_surfaces", []) or []),
            "risk_paths": len(field("risk_paths", []) or []),
            "top_targets": len(field("top_targets", []) or []),
        }
    if name == "brutal":
        score = field("overall_score")
        return {"overall_score": score, "verdict": field("verdict", "")}
    if name == "blast_radius":
        summary = result.get("summary", {}) if isinstance(result, dict) else {}
        components = result.get("components", []) if isinstance(result, dict) else []
        highest = max(components, key=lambda c: c.get("score", 0), default={})
        return {
            "components_analyzed": summary.get("components_analyzed", 0),
            "high_impact_components": summary.get("high_impact_components", 0),
            "highest": {"id": highest.get("id"), "score": highest.get("score")},
        }
    return {}


async def _build_final_report(project_id: str, owner_user_id: str, state: dict) -> dict:
    project = await get_owned_project_metadata(project_id, owner_user_id)
    source_revision = project.get("source_revision") if project else None
    analysis_revision = project.get("analysis_revision") if project else None
    remaining = len(project.get("security_findings") or project.get("findings") or []) if project else 0
    report = {
        "repository_hardened": remaining == 0,
        "defender": {
            "confirmed_findings": state["defender"].get("initial_findings", 0),
            "automatically_fixed": state["defender"].get("fixed", 0),
            "requires_manual_review": remaining,
            "fix_cycles": state["defender"].get("fix_cycles", 0),
        },
        "hacker": {
            "attack_surfaces": state["hacker"].get("attack_surfaces", 0),
            "risk_paths": state["hacker"].get("risk_paths", 0),
            "status": state["hacker"].get("status"),
        },
        "brutal": {
            "overall_score": state["brutal"].get("overall_score"),
            "verdict": state["brutal"].get("verdict"),
            "status": state["brutal"].get("status"),
        },
        "blast_radius": {
            "high_impact_components": state["blast_radius"].get("high_impact_components", 0),
            "highest": state["blast_radius"].get("highest"),
            "status": state["blast_radius"].get("status"),
        },
    }
    state["download"] = {
        "ready": True,
        "source_revision": source_revision,
        "analysis_revision": analysis_revision,
        "fresh": source_revision == analysis_revision,
    }
    return report


async def _run_automation(project_id: str, owner_user_id: str, state: dict) -> None:
    started = time.monotonic()
    print(f"[stage] AUTOMATION_START project_id={project_id}")
    try:
        await _run_defender(project_id, owner_user_id, state)
        if state.get("status") == "stopped":
            return

        project = await get_owned_project_metadata(project_id, owner_user_id)
        await _run_read_only_stage(state, "hacker", "Hacker Mode", lambda: run_hacker_lens(project))

        project = await get_owned_project_metadata(project_id, owner_user_id)
        await _run_read_only_stage(state, "brutal", "Brutal Audit", lambda: run_brutal_audit(project))

        project = await get_owned_project_metadata(project_id, owner_user_id)
        await _run_read_only_stage(state, "blast_radius", "Blast Radius", lambda: build_blast_radius(project))

        state["final_report"] = await _build_final_report(project_id, owner_user_id, state)
        warnings = any(state[s].get("status") == "failed" for s in ("hacker", "brutal", "blast_radius"))
        warnings = warnings or bool(state["defender"].get("manual_review_required"))
        state["status"] = "complete"
        state["warnings"] = warnings
        state["current_stage"] = "complete"
        state["message"] = "Automation complete."
        await _persist(state)
    except Exception as exc:
        state["status"] = "paused"
        state["message"] = "Automation paused because a source-mutating stage could not continue safely."
        state["error"] = f"{type(exc).__name__}: {exc}"
        await _persist(state)
        print(f"[automation] paused project_id={project_id}: {type(exc).__name__}: {exc}")
    finally:
        if state.get("status") in TERMINAL_STATUSES:
            _active_runs.pop(project_id, None)
        print(
            f"[stage] AUTOMATION_COMPLETE project_id={project_id} status={state.get('status')} "
            f"duration_ms={round((time.monotonic() - started) * 1000)}"
        )
