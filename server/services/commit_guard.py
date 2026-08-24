"""Commit Guard: orchestrates git truth, security truth, and impact truth
into one deterministic PASS/REVIEW/BLOCK verdict, with a Groq explanation
that can never influence the verdict itself.

Golden rule, enforced structurally by this file's own control flow:
    Git Diff       = git truth        (services.git_history)
    Defender       = security truth   (services.commit_guard_security ->
                      the same to_closed_world_findings gate every other
                      SAGE feature uses -- no second, weaker scanner)
    Blast Radius   = impact truth     (services.commit_guard_impact)
    Backend policy = verdict truth    (_compute_verdict below, pure function)
    Groq           = explanation only (never writes to verdict/score/findings)

Commit Guard is READ ONLY: it never applies a patch, never calls Fix All,
never mutates the project's source. It only ever reads GitHub (via
git_history.py, HTTPS API calls, no local git/subprocess) and the project's
own metadata (owner/repo, for resolving which GitHub repo to compare).
"""

import ast
import asyncio
import time
from datetime import datetime, timezone

from db.mongo import (
    create_commit_guard_run,
    get_owned_latest_commit_guard_run,
    get_owned_commit_guard_report,
    get_owned_project_metadata,
    update_commit_guard_run,
)
from services.commit_guard_impact import compute_blast_delta, detect_sensitive_areas
from services.commit_guard_security import compute_security_delta
from services.git_history import (
    ChangedFile,
    CommitInfo,
    GitHistoryUnavailable,
    MAX_CHANGED_PYTHON_FILES,
    fetch_snapshot,
    resolve_latest_commit,
)
from services.groq_client import GroqUnavailableError, call_groq
from services.prompt_builder import build_commit_guard_prompt
from services.project_review import GLOBAL_AI_SEMAPHORE
from services.reasoning_engine import _extract_json

_SEVERITY_WEIGHT = {"critical": 45, "high": 30, "medium": 15, "low": 6}
_MAX_SEVERITY_SUBSCORE = 100

# One in-memory, per-project registry -- same architecture as
# services/fix_all.py and services/analysis_jobs.py (single-process demo
# deployment, documented there; not repeated here).
_active_runs: dict[str, dict] = {}
_guard = asyncio.Lock()
_job_counter = 0


def is_commit_guard_running(project_id: str) -> bool:
    state = _active_runs.get(project_id)
    return bool(state and state["status"] == "running")


def _public_state(state: dict) -> dict:
    return {
        "job_id": state.get("job_id"),
        "project_id": state.get("project_id"),
        "status": state.get("status"),
        "stage": state.get("stage"),
        "message": state.get("message", ""),
        "head_sha": state.get("head_sha"),
        "base_sha": state.get("base_sha"),
        "report": state.get("report"),
        "error": state.get("error"),
    }


async def _persist(state: dict) -> None:
    run_id = state.get("run_id")
    if not run_id:
        return
    try:
        await update_commit_guard_run(run_id, state["owner_user_id"], _public_state(state))
    except Exception as exc:
        print(f"[commit-guard] persistence update failed project_id={state.get('project_id')}: {type(exc).__name__}: {exc}")


async def _set_stage(state: dict, stage: str, message: str) -> None:
    state["stage"] = stage
    state["message"] = message
    await _persist(state)


async def get_commit_guard_status(project_id: str, owner_user_id: str) -> dict | None:
    state = _active_runs.get(project_id)
    if state and state.get("owner_user_id") == owner_user_id:
        return _public_state(state)
    try:
        run = await get_owned_latest_commit_guard_run(project_id, owner_user_id)
    except Exception as exc:
        print(f"[commit-guard] persisted status lookup failed project_id={project_id}: {type(exc).__name__}: {exc}")
        return None
    if run is None:
        return None
    if run.get("status") == "running":
        run["status"] = "failed"
        run["stage"] = "failed"
        run["error"] = "Commit Guard was interrupted because the server restarted. Start a new run to continue."
    return {
        "job_id": run.get("job_id"),
        "project_id": run.get("project_id"),
        "status": run.get("status"),
        "stage": run.get("stage"),
        "message": run.get("message", ""),
        "head_sha": run.get("head_sha"),
        "base_sha": run.get("base_sha"),
        "report": run.get("report"),
        "error": run.get("error"),
    }


def _changed_python_files(info: CommitInfo) -> list[ChangedFile]:
    return [f for f in info.changed_files if f.path.endswith(".py") or f.path.endswith(".pyi")][:MAX_CHANGED_PYTHON_FILES]


def _static_validity(head_snapshot: dict[str, str], changed_paths: list[str]) -> tuple[bool, list[str]]:
    """True if every changed Python file parses as valid Python at HEAD.
    Never imports/executes the module -- ast.parse only inspects syntax."""
    broken = []
    for path in changed_paths:
        content = head_snapshot.get(path)
        if content is None:
            continue  # removed file, nothing to validate at HEAD
        try:
            ast.parse(content)
        except SyntaxError:
            broken.append(path)
    return (not broken, broken)


def _security_subscore(new_findings: list[dict]) -> int:
    total = sum(_SEVERITY_WEIGHT.get(f.get("severity", "low"), 6) for f in new_findings)
    return min(_MAX_SEVERITY_SUBSCORE, total)


def _blast_subscore(blast_summary: dict) -> int:
    # overall_delta is on the same 0-10 scale blast_radius.py already scores
    # components on; scaled to 0-100 and clamped both directions (an
    # improved/reduced blast footprint contributes 0, never a negative score).
    delta = blast_summary.get("overall_delta", 0) or 0
    return max(0, min(100, round(delta * 10)))


def _sensitive_subscore(sensitive_areas: list[str]) -> int:
    if not sensitive_areas:
        return 0
    score = min(70, 25 * len(sensitive_areas))
    if any(tag in sensitive_areas for tag in ("admin", "privileged_operation", "authentication")):
        score = min(100, score + 20)
    return score


def _risk_score(security_sub: int, blast_sub: int, sensitive_sub: int, validity_sub: int) -> int:
    return round(0.50 * security_sub + 0.25 * blast_sub + 0.20 * sensitive_sub + 0.05 * validity_sub)


def _compute_verdict(
    new_findings: list[dict],
    resolved_findings: list[dict],
    blast_summary: dict,
    sensitive_areas: list[str],
    validity_ok: bool,
) -> tuple[str, int]:
    """Pure, deterministic. The ONLY function allowed to decide PASS/REVIEW/
    BLOCK. Nothing downstream of this (Groq included) may override it."""
    security_sub = _security_subscore(new_findings)
    blast_sub = _blast_subscore(blast_summary)
    sensitive_sub = _sensitive_subscore(sensitive_areas)
    validity_sub = 0 if validity_ok else 100
    score = _risk_score(security_sub, blast_sub, sensitive_sub, validity_sub)

    new_severities = {f.get("severity") for f in new_findings}
    if not validity_ok or "critical" in new_severities:
        return "BLOCK", score

    if "high" in new_severities:
        return "REVIEW", score

    significant_blast = blast_summary.get("overall_delta", 0) >= 2.0
    if significant_blast and sensitive_areas:
        return "REVIEW", score

    medium_in_sensitive_count = sum(
        1 for f in new_findings if f.get("severity") == "medium"
    )
    if medium_in_sensitive_count >= 2 and sensitive_areas:
        return "REVIEW", score

    return "PASS", score


def _docs_only_result(info: CommitInfo) -> dict:
    return _build_report_shape(
        info=info,
        security_delta={"base_findings": [], "head_findings": [], "new": [], "resolved": [], "persisting": []},
        blast_delta={"components": [], "summary": {"overall_before": 0, "overall_after": 0, "overall_delta": 0, "affected_routes_before": 0, "affected_routes_after": 0}},
        sensitive_areas=[],
        validity_ok=True,
        broken_files=[],
        verdict="PASS",
        risk_score=0,
        summary="No analyzable Python source changes detected.",
        ai_explanation="",
        ai_error="",
    )


def _build_report_shape(
    *, info: CommitInfo, security_delta: dict, blast_delta: dict, sensitive_areas: list[str],
    validity_ok: bool, broken_files: list[str], verdict: str, risk_score: int,
    summary: str, ai_explanation: str, ai_error: str,
) -> dict:
    return {
        "head_sha": info.head_sha,
        "base_sha": info.base_sha,
        "comparison_type": info.comparison_type,
        "merge_commit": info.merge_commit,
        "parent_count": info.parent_count,
        "comparison_parent": info.comparison_parent,
        "commit_message": info.message,
        "commit_author": info.author,
        "commit_authored_at": info.authored_at,
        "changed_files": [
            {"path": f.path, "status": f.status, "previous_path": f.previous_path, "additions": f.additions, "deletions": f.deletions, "patch": f.patch}
            for f in info.changed_files
        ],
        "truncated": info.truncated,
        "security_delta": {
            "new": security_delta["new"],
            "resolved": security_delta["resolved"],
            "persisting": security_delta["persisting"],
        },
        "blast_delta": blast_delta,
        "sensitive_areas": sensitive_areas,
        "static_validity": {"valid": validity_ok, "broken_files": broken_files},
        "risk_score": risk_score,
        "verdict": verdict,
        "summary": summary,
        "ai_explanation": ai_explanation,
        "ai_error": ai_error,
    }


async def _generate_explanation(report: dict) -> tuple[str, str]:
    """Groq is explanation-only -- it receives the already-final verdict/
    score/findings as read-only context and can never change them. Returns
    (explanation, error) -- error non-empty means explanation unavailable,
    the rest of the report is still returned to the caller regardless."""
    bounded_context = {
        "commit": {"message": report["commit_message"][:500], "head_sha": report["head_sha"], "base_sha": report["base_sha"]},
        "changed_components": [f["path"] for f in report["changed_files"]][:60],
        "security_delta": {
            "new": [{"rule_id": f.get("rule_id"), "file": f.get("file"), "severity": f.get("severity")} for f in report["security_delta"]["new"]][:20],
            "resolved": [{"rule_id": f.get("rule_id"), "file": f.get("file")} for f in report["security_delta"]["resolved"]][:20],
        },
        "blast_delta": report["blast_delta"]["summary"],
        "sensitive_areas": report["sensitive_areas"],
        "verdict": report["verdict"],
    }
    prompt = build_commit_guard_prompt(bounded_context)
    messages = [{"role": "user", "content": prompt}]
    try:
        async with GLOBAL_AI_SEMAPHORE:
            raw = await call_groq(messages)
        parsed = _extract_json(raw)
        if parsed is None:
            async with GLOBAL_AI_SEMAPHORE:
                raw = await call_groq([{"role": "user", "content": prompt + "\n\nRespond with ONLY the JSON object, nothing else."}])
            parsed = _extract_json(raw)
    except GroqUnavailableError as exc:
        return "", str(exc)
    if not isinstance(parsed, dict):
        return "", "invalid_model_output"
    explanation = parsed.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        return "", "invalid_model_output"
    return explanation.strip()[:2000], ""


async def _run(project_id: str, owner_user_id: str, state: dict) -> None:
    stage_start = time.monotonic()
    print(f"[stage] COMMIT_GUARD_START project_id={project_id}")
    state.setdefault("project_id", project_id)
    state.setdefault("owner_user_id", owner_user_id)
    state.setdefault("status", "running")
    state.setdefault("stage", "queued")
    state.setdefault("message", "Commit Guard queued.")
    state.setdefault("report", None)
    state.setdefault("error", None)
    try:
        await _set_stage(state, "resolving_commit", "Resolving the latest Git commit.")
        project = await get_owned_project_metadata(project_id, owner_user_id)
        if project is None:
            state["status"] = "failed"
            state["stage"] = "failed"
            state["error"] = "Project not found."
            await _persist(state)
            return

        owner = project.get("github_owner")
        repo = project.get("github_repo")
        if not owner or not repo:
            state["status"] = "failed"
            state["stage"] = "failed"
            state["error"] = (
                "Git history unavailable. Commit Guard requires a repository imported "
                "from GitHub or another source with verifiable commit history."
            )
            await _persist(state)
            return

        try:
            info = await resolve_latest_commit(owner, repo)
        except GitHistoryUnavailable as exc:
            state["status"] = "failed"
            state["stage"] = "failed"
            state["error"] = str(exc)
            await _persist(state)
            return
        state["head_sha"] = info.head_sha
        state["base_sha"] = info.base_sha

        # Cache: an identical (base_sha, head_sha) comparison for this
        # project never needs to redo Defender/blast/Groq work.
        cached = await get_owned_commit_guard_report(project_id, owner_user_id, info.base_sha, info.head_sha)
        if cached is not None:
            state["report"] = cached["report"]
            state["status"] = "completed"
            state["stage"] = "complete"
            state["message"] = "Commit Guard loaded from cache."
            await _persist(state)
            print(f"[stage] COMMIT_GUARD_COMPLETE project_id={project_id} cache_hit=true duration_ms={round((time.monotonic() - stage_start) * 1000)}")
            return

        if not state.get("run_id"):
            try:
                run_id = await create_commit_guard_run(
                    project_id,
                    owner_user_id,
                    info.base_sha,
                    info.head_sha,
                    None,
                    state=_public_state(state),
                )
                state["run_id"] = run_id
                state["job_id"] = run_id
            except Exception as exc:
                print(f"[commit-guard] persistence unavailable, continuing in-memory only: {type(exc).__name__}: {exc}")
        await _persist(state)

        python_files = _changed_python_files(info)
        if not python_files:
            state["report"] = _docs_only_result(info)
            state["status"] = "completed"
            state["stage"] = "complete"
            state["message"] = "Commit Guard completed with no analyzable Python source changes."
            await _persist(state)
            print(f"[stage] COMMIT_GUARD_COMPLETE project_id={project_id} docs_only=true duration_ms={round((time.monotonic() - stage_start) * 1000)}")
            return

        await _set_stage(state, "building_diff", "Building the BASE to HEAD Python diff.")
        changed_paths = [f.path for f in python_files]
        renamed_paths = {f.path: f.previous_path for f in python_files if f.status == "renamed" and f.previous_path}
        base_paths = [f.previous_path or f.path for f in python_files if f.status != "added"]

        head_snapshot = await fetch_snapshot(owner, repo, changed_paths, info.head_sha)
        base_snapshot = await fetch_snapshot(owner, repo, base_paths, info.base_sha)

        await _set_stage(state, "comparing_security", "Comparing Defender findings before and after the commit.")
        security_delta = await compute_security_delta(base_snapshot, head_snapshot, renamed_paths)
        await _set_stage(state, "mapping_impact", "Mapping deterministic blast radius impact.")
        blast_delta = await compute_blast_delta(base_snapshot, head_snapshot, changed_paths)
        sensitive_areas = detect_sensitive_areas(head_snapshot, changed_paths)
        validity_ok, broken_files = _static_validity(head_snapshot, changed_paths)

        await _set_stage(state, "calculating_risk", "Calculating deterministic commit risk.")
        verdict, risk_score = _compute_verdict(
            security_delta["new"], security_delta["resolved"], blast_delta["summary"], sensitive_areas, validity_ok
        )

        if not security_delta["new"] and security_delta["resolved"] and blast_delta["summary"].get("overall_delta", 0) <= 0:
            summary = "This commit improves the security posture."
        elif not python_files:
            summary = "No analyzable Python source changes detected."
        else:
            summary = f"{len(security_delta['new'])} new finding(s), {len(security_delta['resolved'])} resolved."

        report = _build_report_shape(
            info=info, security_delta=security_delta, blast_delta=blast_delta,
            sensitive_areas=sensitive_areas, validity_ok=validity_ok, broken_files=broken_files,
            verdict=verdict, risk_score=risk_score, summary=summary, ai_explanation="", ai_error="",
        )

        await _set_stage(state, "generating_explanation", "Generating explanation without changing verdict.")
        explanation, ai_error = await _generate_explanation(report)
        report["ai_explanation"] = explanation
        report["ai_error"] = ai_error
        # Groq ran AFTER the verdict was already fixed above -- structurally
        # impossible for it to have influenced verdict/risk_score/findings.

        state["report"] = report
        state["status"] = "completed"
        state["stage"] = "complete"
        state["message"] = "Commit Guard complete."
        await _persist(state)
        print(
            f"[stage] COMMIT_GUARD_COMPLETE project_id={project_id} verdict={verdict} risk_score={risk_score} "
            f"new_findings={len(security_delta['new'])} duration_ms={round((time.monotonic() - stage_start) * 1000)}"
        )
    except Exception as exc:
        state["status"] = "failed"
        state["stage"] = "failed"
        state["error"] = f"Commit Guard failed: {type(exc).__name__}"
        await _persist(state)
        print(f"[commit-guard] unhandled error project_id={project_id}: {exc}")
    finally:
        async with _guard:
            if _active_runs.get(project_id, {}).get("job_id") == state.get("job_id"):
                if state["status"] == "running":
                    state["status"] = "failed"
                    state["error"] = state.get("error") or "Commit Guard ended unexpectedly."
                _active_runs.pop(project_id, None)


async def start_commit_guard(project_id: str, owner_user_id: str) -> dict:
    """Start (or return the already-running) Commit Guard job for this
    project -- duplicate clicks for the same project never spawn a second
    concurrent run."""
    global _job_counter
    async with _guard:
        existing = _active_runs.get(project_id)
        if existing and existing["status"] == "running":
            return existing
        _job_counter += 1
        state = {
            "job_id": f"commitguard-{project_id}-{_job_counter}",
            "project_id": project_id,
            "owner_user_id": owner_user_id,
            "status": "running",
            "stage": "queued",
            "message": "Commit Guard queued.",
            "report": None,
            "error": None,
        }
        _active_runs[project_id] = state
    asyncio.create_task(_run(project_id, owner_user_id, state), name=f"commit-guard:{project_id}")
    return state
