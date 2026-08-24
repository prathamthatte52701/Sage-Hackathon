"""PR Guard: analyzes one GitHub pull request as a combined change-set.

This intentionally reuses Commit Guard primitives for source snapshots,
closed-world security deltas, blast deltas, static validity, and deterministic
verdicting. It is read-only: no checkout, no merge, no branch mutation, no Fix
All, and no GitHub write API calls.
"""

from __future__ import annotations

import ast
import asyncio
import re
import time

from db.mongo import (
    create_pr_guard_run,
    get_owned_pr_guard_cached_report,
    get_owned_pr_guard_run,
    get_owned_project_metadata,
    update_pr_guard_run,
)
from services.commit_guard_impact import compute_blast_delta, detect_sensitive_areas
from services.commit_guard_security import compute_security_delta
from services.git_history import (
    ChangedFile,
    GitHistoryUnavailable,
    PullRequestInfo,
    fetch_snapshot,
    resolve_pull_request,
    resolve_pull_request_head_sha,
)
from services.groq_client import GroqUnavailableError, call_groq
from services.prompt_builder import build_pr_guard_hacker_prompt, build_pr_guard_prompt
from services.project_review import GLOBAL_AI_SEMAPHORE
from services.reasoning_engine import _extract_json
from services.structural.python_ast import analyze_python_source

_SEVERITY_WEIGHT = {"critical": 45, "high": 30, "medium": 15, "low": 6}
_QUALITY_DIMENSIONS = ("architecture", "reliability", "maintainability", "code_quality", "production_readiness")
_TERMINAL = {"complete", "failed"}

_SYNC_HTTP_RE = re.compile(r"\brequests\.(get|post|put|patch|delete)\s*\(", re.I)
_TIMEOUT_RE = re.compile(r"\btimeout\s*=")
_BROAD_EXCEPT_RE = re.compile(r"except\s+(Exception|BaseException)?\s*:\s*(pass|return\s+None|return\s*\{\})", re.I)
_CACHE_RE = re.compile(r"(?i)\b(cache|memo|registry)\s*=\s*(\{\}|\[\])")
_DB_RE = re.compile(r"(?i)\b(sqlite3|sqlalchemy|pymongo|database|db\.|cursor\(|execute\(|query\()")
_FS_RE = re.compile(r"(?i)\b(open\(|Path\(|read_text\(|write_text\(|unlink\(|rmtree\(|shutil\.|zipfile\.)")
_AUTH_RE = re.compile(r"(?i)\b(auth|login|logout|jwt|session|password|permission|role|admin|privileg)")

_active_runs: dict[str, dict] = {}
_active_by_project_pr: dict[tuple[str, int], str] = {}
_guard = asyncio.Lock()
_counter = 0


def _public_state(state: dict) -> dict:
    return {
        "run_id": state.get("run_id"),
        "job_id": state.get("job_id"),
        "project_id": state.get("project_id"),
        "pull_request_number": state.get("pull_request_number"),
        "status": state.get("status"),
        "stage": state.get("stage"),
        "message": state.get("message", ""),
        "merge_base_sha": state.get("merge_base_sha"),
        "head_sha": state.get("head_sha"),
        "report": state.get("report"),
        "error": state.get("error"),
    }


async def _persist(state: dict) -> None:
    run_id = state.get("run_id")
    if not run_id:
        return
    try:
        await update_pr_guard_run(run_id, state["owner_user_id"], _public_state(state))
    except Exception as exc:
        print(f"[pr-guard] persistence update failed project_id={state.get('project_id')}: {type(exc).__name__}: {exc}")


async def _set_stage(state: dict, stage: str, message: str = "") -> None:
    state["stage"] = stage
    state["message"] = message
    await _persist(state)


def _changed_python_files(info: PullRequestInfo) -> list[ChangedFile]:
    return [f for f in info.changed_files if f.path.endswith(".py") or f.path.endswith(".pyi")]


def _static_validity(head_snapshot: dict[str, str], changed_paths: list[str]) -> tuple[bool, list[str]]:
    broken = []
    for path in changed_paths:
        content = head_snapshot.get(path)
        if content is None:
            continue
        try:
            ast.parse(content)
        except SyntaxError:
            broken.append(path)
    return (not broken, broken)


def _security_subscore(new_findings: list[dict]) -> int:
    total = sum(_SEVERITY_WEIGHT.get(f.get("severity", "low"), 6) for f in new_findings)
    return min(100, total)


def _blast_subscore(blast_summary: dict) -> int:
    delta = blast_summary.get("overall_delta", 0) or 0
    route_delta = max(0, int(blast_summary.get("affected_routes_after", 0)) - int(blast_summary.get("affected_routes_before", 0)))
    return max(0, min(100, round(delta * 8) + min(30, route_delta * 6)))


def _sensitive_subscore(sensitive_areas: list[str]) -> int:
    if not sensitive_areas:
        return 0
    score = min(75, 18 * len(sensitive_areas))
    if any(tag in sensitive_areas for tag in ("authentication", "admin", "privileged_operation")):
        score = min(100, score + 20)
    return score


def _quality_penalties(snapshot: dict[str, str], paths: list[str]) -> dict[str, int]:
    penalties = dict.fromkeys(_QUALITY_DIMENSIONS, 0)
    for path in paths:
        content = snapshot.get(path) or ""
        if not content:
            continue
        sync_http = len(_SYNC_HTTP_RE.findall(content))
        timeout_mentions = len(_TIMEOUT_RE.findall(content))
        no_timeout_http = max(0, sync_http - timeout_mentions)
        penalties["reliability"] += no_timeout_http * 18
        penalties["production_readiness"] += no_timeout_http * 12
        penalties["reliability"] += len(_BROAD_EXCEPT_RE.findall(content)) * 15
        penalties["maintainability"] += len(_CACHE_RE.findall(content)) * 8
        if _DB_RE.search(content) and _AUTH_RE.search(content):
            penalties["architecture"] += 10
            penalties["security" if "security" in penalties else "production_readiness"] = penalties.get("security", 0) + 0
        if _FS_RE.search(content):
            penalties["production_readiness"] += 6
        if len(content.splitlines()) > 450:
            penalties["maintainability"] += 12
            penalties["code_quality"] += 8
    return {k: min(100, v) for k, v in penalties.items()}


def _compute_quality_delta(base_snapshot: dict[str, str], head_snapshot: dict[str, str], changed_paths: list[str]) -> dict:
    base = _quality_penalties(base_snapshot, changed_paths)
    head = _quality_penalties(head_snapshot, changed_paths)
    dimensions = {}
    degraded = 0
    improved = 0
    for name in _QUALITY_DIMENSIONS:
        before = round(max(0.0, 10.0 - base.get(name, 0) / 10), 1)
        after = round(max(0.0, 10.0 - head.get(name, 0) / 10), 1)
        delta = round(after - before, 1)
        if delta < 0:
            degraded += abs(delta)
        elif delta > 0:
            improved += delta
        dimensions[name] = {
            "before": before,
            "after": after,
            "delta": delta,
            "direction": "DEGRADED" if delta < 0 else "IMPROVED" if delta > 0 else "UNCHANGED",
        }
    overall_delta = round(sum(item["delta"] for item in dimensions.values()) / len(dimensions), 1)
    if degraded > improved:
        direction = "DEGRADED"
    elif improved > degraded:
        direction = "IMPROVED"
    else:
        direction = "UNCHANGED"
    return {"dimensions": dimensions, "overall_delta": overall_delta, "direction": direction}


def _quality_subscore(quality_delta: dict) -> int:
    degraded = [
        abs(float(item.get("delta", 0)))
        for item in (quality_delta.get("dimensions") or {}).values()
        if float(item.get("delta", 0)) < 0
    ]
    return min(100, round(sum(degraded) * 12))


def _risk_score(security_sub: int, blast_sub: int, sensitive_sub: int, quality_sub: int, validity_sub: int) -> int:
    return round(0.45 * security_sub + 0.20 * blast_sub + 0.15 * sensitive_sub + 0.15 * quality_sub + 0.05 * validity_sub)


def _compute_verdict(
    new_findings: list[dict],
    blast_summary: dict,
    sensitive_areas: list[str],
    quality_delta: dict,
    validity_ok: bool,
) -> tuple[str, int]:
    security_sub = _security_subscore(new_findings)
    blast_sub = _blast_subscore(blast_summary)
    sensitive_sub = _sensitive_subscore(sensitive_areas)
    quality_sub = _quality_subscore(quality_delta)
    validity_sub = 0 if validity_ok else 100
    score = _risk_score(security_sub, blast_sub, sensitive_sub, quality_sub, validity_sub)

    severities = {f.get("severity") for f in new_findings}
    if not validity_ok or "critical" in severities:
        return "BLOCK", score
    if "high" in severities:
        return "REVIEW", score
    if blast_summary.get("overall_delta", 0) >= 2.0 and sensitive_areas:
        return "REVIEW", score
    if quality_delta.get("direction") == "DEGRADED" and quality_sub >= 30:
        return "REVIEW", score
    medium_count = sum(1 for f in new_findings if f.get("severity") == "medium")
    if medium_count >= 2 and sensitive_areas:
        return "REVIEW", score
    return "PASS", score


def _change_map(info: PullRequestInfo, head_snapshot: dict[str, str], changed_paths: list[str]) -> dict:
    entry_points = []
    handlers = []
    business_logic = []
    auth = []
    db_access = []
    filesystem = []
    outbound_http = []
    functions_changed = 0
    classes_changed = 0
    routes_changed = 0
    imports_changed = 0

    for path in changed_paths:
        content = head_snapshot.get(path) or ""
        lowered = path.lower()
        module = analyze_python_source(content)
        funcs = [fn.name for fn in module.functions[:30]]
        classes = [cls.name for cls in module.classes[:20]]
        routes = [
            {"method": route["method"], "path": route["path"], "line": route["line"], "handler": fn.name}
            for fn in module.functions
            for route in fn.routes
        ]
        functions_changed += len(funcs)
        classes_changed += len(classes)
        routes_changed += len(routes)
        imports_changed += len(module.imports)

        if routes or any(token in lowered for token in ("route", "view", "api", "app.py", "main.py")):
            entry_points.append(path)
            handlers.extend({"file": path, **route} for route in routes[:12])
        if _AUTH_RE.search(content) or _AUTH_RE.search(path):
            auth.append(path)
        if _DB_RE.search(content):
            db_access.append(path)
        if _FS_RE.search(content):
            filesystem.append(path)
        if _SYNC_HTTP_RE.search(content) or "httpx." in content or "urllib." in content:
            outbound_http.append(path)
        if funcs or classes:
            business_logic.append(path)

    return {
        "changed_components": changed_paths,
        "files_changed": info.changed_file_count,
        "python_files_changed": len(changed_paths),
        "lines_added": info.additions,
        "lines_deleted": info.deletions,
        "functions_changed": functions_changed,
        "classes_changed": classes_changed,
        "routes_changed": routes_changed,
        "imports_changed": imports_changed,
        "changed_entry_points": sorted(set(entry_points)),
        "changed_handlers": handlers[:30],
        "changed_business_logic": sorted(set(business_logic)),
        "changed_auth_authz": sorted(set(auth)),
        "db_access": sorted(set(db_access)),
        "filesystem_access": sorted(set(filesystem)),
        "outbound_http": sorted(set(outbound_http)),
        "sensitive_configuration": [f.path for f in info.changed_files if "requirements" in f.path.lower() or f.path.lower().endswith((".env.example", "pyproject.toml"))],
        "privileged_functionality": sorted(set(auth + filesystem)),
    }


def _summary(security_delta: dict, quality_delta: dict, docs_only: bool) -> str:
    if docs_only:
        return "This PR has no analyzable Python source changes."
    if not security_delta["new"] and security_delta["resolved"]:
        return "This PR improves repository security posture."
    return f"{len(security_delta['new'])} new, {len(security_delta['resolved'])} resolved, {len(security_delta['persisting'])} persisting confirmed finding(s); quality impact is {quality_delta.get('direction', 'UNCHANGED').lower()}."


def _build_report(
    *,
    info: PullRequestInfo,
    security_delta: dict,
    blast_delta: dict,
    sensitive_areas: list[str],
    quality_delta: dict,
    change_map: dict,
    validity_ok: bool,
    broken_files: list[str],
    verdict: str,
    risk_score: int,
    summary: str,
    hacker_review: dict,
    ai_explanation: str,
    ai_error: str,
) -> dict:
    return {
        "pr": {
            "number": info.number,
            "title": info.title,
            "state": info.state,
            "merged": info.merged,
            "author": info.author,
            "base_branch": info.base_branch,
            "head_branch": info.head_branch,
            "commit_count": info.commit_count,
            "changed_file_count": info.changed_file_count,
            "additions": info.additions,
            "deletions": info.deletions,
        },
        "comparison_base": info.merge_base_sha,
        "comparison_head": info.head_sha,
        "merge_base": info.merge_base_sha,
        "base_sha": info.base_sha,
        "head_sha": info.head_sha,
        "changed_files": [
            {"path": f.path, "status": f.status, "previous_path": f.previous_path, "additions": f.additions, "deletions": f.deletions, "patch": f.patch}
            for f in info.changed_files
        ],
        "truncated": info.truncated,
        "change_map": change_map,
        "security_delta": {
            "new": security_delta["new"],
            "resolved": security_delta["resolved"],
            "persisting": security_delta["persisting"],
        },
        "blast_delta": blast_delta,
        "sensitive_areas": sensitive_areas,
        "quality_delta": quality_delta,
        "hacker_review": hacker_review,
        "static_validity": {"valid": validity_ok, "broken_files": broken_files},
        "risk_score": risk_score,
        "verdict": verdict,
        "summary": summary,
        "ai_explanation": ai_explanation,
        "ai_error": ai_error,
        "stale": False,
        "current_head_sha": info.head_sha,
    }


async def _generate_hacker_review(report_context: dict) -> dict:
    prompt = build_pr_guard_hacker_prompt(report_context)
    try:
        async with GLOBAL_AI_SEMAPHORE:
            raw = await call_groq([{"role": "user", "content": prompt}], temperature=0.0)
        parsed = _extract_json(raw)
        if parsed is None:
            return {"summary": "Adversarial PR review unavailable: invalid model output.", "error": "invalid_model_output", "hypotheses": [], "priorities": []}
    except GroqUnavailableError as exc:
        return {"summary": "Adversarial PR review unavailable.", "error": str(exc), "hypotheses": [], "priorities": []}
    if not isinstance(parsed, dict):
        return {"summary": "Adversarial PR review unavailable: invalid model output.", "error": "invalid_model_output", "hypotheses": [], "priorities": []}
    valid_paths = set(report_context.get("changed_components", []))
    priorities = [
        item.strip()
        for item in parsed.get("review_priorities", [])
        if isinstance(item, str) and item.strip() and (not valid_paths or any(path in item for path in valid_paths))
    ][:5]
    hypotheses = [
        item.strip()
        for item in parsed.get("hacker_hypotheses", [])
        if isinstance(item, str) and item.strip()
    ][:5]
    summary = parsed.get("summary") if isinstance(parsed.get("summary"), str) else ""
    return {"summary": summary.strip(), "error": "", "hypotheses": hypotheses, "priorities": priorities, "label": "HYPOTHESES - NOT CONFIRMED FINDINGS"}


async def _generate_explanation(report: dict) -> tuple[str, str]:
    context = {
        "pr": report["pr"],
        "changed_files": report["pr"]["changed_file_count"],
        "comparison_base": report["comparison_base"],
        "comparison_head": report["comparison_head"],
        "security_delta": {
            "new": len(report["security_delta"]["new"]),
            "resolved": len(report["security_delta"]["resolved"]),
            "persisting": len(report["security_delta"]["persisting"]),
        },
        "blast_delta": report["blast_delta"]["summary"],
        "sensitive_surfaces": report["sensitive_areas"],
        "quality_delta": report["quality_delta"],
        "backend_verdict": report["verdict"],
        "risk_score": report["risk_score"],
    }
    prompt = build_pr_guard_prompt(context)
    try:
        async with GLOBAL_AI_SEMAPHORE:
            raw = await call_groq([{"role": "user", "content": prompt}], temperature=0.0)
        parsed = _extract_json(raw)
    except GroqUnavailableError as exc:
        return "", str(exc)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("explanation"), str):
        return "", "invalid_model_output"
    return parsed["explanation"].strip()[:2000], ""


async def _run(project_id: str, owner_user_id: str, pr_number: int, state: dict) -> None:
    started = time.monotonic()
    print(f"[stage] PR_GUARD_START project_id={project_id} pr={pr_number}")
    try:
        await _set_stage(state, "resolving_pr", "Resolving GitHub pull request.")
        project = await get_owned_project_metadata(project_id, owner_user_id)
        if project is None:
            state["status"] = "failed"
            state["error"] = "Project not found."
            await _persist(state)
            return
        owner = project.get("github_owner")
        repo = project.get("github_repo")
        if not owner or not repo:
            state["status"] = "failed"
            state["error"] = "PR Guard requires a GitHub-backed project."
            await _persist(state)
            return

        try:
            info = await resolve_pull_request(owner, repo, pr_number)
        except GitHistoryUnavailable as exc:
            state["status"] = "failed"
            state["error"] = str(exc)
            await _persist(state)
            return

        if info.state != "open" or info.merged:
            state["message"] = "This PR is not open; analysis is read-only and shown for reference."
        state["merge_base_sha"] = info.merge_base_sha
        state["head_sha"] = info.head_sha
        await _persist(state)

        cached = await get_owned_pr_guard_cached_report(project_id, owner_user_id, pr_number, info.merge_base_sha, info.head_sha)
        if cached is not None:
            state["report"] = cached["report"]
            state["status"] = "complete"
            state["stage"] = "complete"
            await _persist(state)
            return

        python_files = _changed_python_files(info)
        changed_paths = [f.path for f in python_files]
        renamed_paths = {f.path: f.previous_path for f in python_files if f.status == "renamed" and f.previous_path}
        base_paths = [f.previous_path or f.path for f in python_files if f.status != "added"]

        await _set_stage(state, "building_diff", "Building one combined PR diff.")
        if not python_files:
            empty_delta = {"base_findings": [], "head_findings": [], "new": [], "resolved": [], "persisting": []}
            blast_delta = {"components": [], "summary": {"overall_before": 0, "overall_after": 0, "overall_delta": 0, "affected_routes_before": 0, "affected_routes_after": 0}}
            quality_delta = {"dimensions": {name: {"before": 10.0, "after": 10.0, "delta": 0.0, "direction": "UNCHANGED"} for name in _QUALITY_DIMENSIONS}, "overall_delta": 0.0, "direction": "UNCHANGED"}
            report = _build_report(
                info=info,
                security_delta=empty_delta,
                blast_delta=blast_delta,
                sensitive_areas=[],
                quality_delta=quality_delta,
                change_map=_change_map(info, {}, []),
                validity_ok=True,
                broken_files=[],
                verdict="PASS",
                risk_score=0,
                summary=_summary(empty_delta, quality_delta, True),
                hacker_review={"summary": "No Python source changes to review adversarially.", "error": "", "hypotheses": [], "priorities": [], "label": "HYPOTHESES - NOT CONFIRMED FINDINGS"},
                ai_explanation="",
                ai_error="",
            )
            state["report"] = report
            state["status"] = "complete"
            state["stage"] = "complete"
            await _persist(state)
            print(f"[stage] PR_GUARD_COMPLETE project_id={project_id} pr={pr_number} docs_only=true")
            return

        head_snapshot = await fetch_snapshot(owner, repo, changed_paths, info.head_sha)
        base_snapshot = await fetch_snapshot(owner, repo, base_paths, info.merge_base_sha)

        await _set_stage(state, "mapping_changes", "Mapping changed Python components.")
        change_map = _change_map(info, head_snapshot, changed_paths)

        await _set_stage(state, "mapping_impact", "Expanding evidence-backed blast radius.")
        blast_delta = await compute_blast_delta(base_snapshot, head_snapshot, changed_paths)
        sensitive_areas = detect_sensitive_areas(head_snapshot, changed_paths)

        await _set_stage(state, "analyzing_base", "Running Defender on merge-base snapshot.")
        await _set_stage(state, "analyzing_head", "Running Defender on PR HEAD snapshot.")
        security_delta = await compute_security_delta(base_snapshot, head_snapshot, renamed_paths)

        await _set_stage(state, "evaluating_quality", "Calculating deterministic quality delta.")
        quality_delta = _compute_quality_delta(base_snapshot, head_snapshot, changed_paths)
        validity_ok, broken_files = _static_validity(head_snapshot, changed_paths)

        await _set_stage(state, "calculating_risk", "Calculating deterministic PR risk score.")
        verdict, risk_score = _compute_verdict(security_delta["new"], blast_delta["summary"], sensitive_areas, quality_delta, validity_ok)

        report_context = {
            "pr": {"number": info.number, "title": info.title[:300], "base": info.base_branch, "head": info.head_branch},
            "changed_components": changed_paths[:60],
            "change_map": change_map,
            "security_delta": {"new": len(security_delta["new"]), "resolved": len(security_delta["resolved"]), "persisting": len(security_delta["persisting"])},
            "sensitive_areas": sensitive_areas,
            "verdict": verdict,
        }
        await _set_stage(state, "running_hacker_review", "Running bounded PR-focused adversarial review.")
        hacker_review = await _generate_hacker_review(report_context)

        report = _build_report(
            info=info,
            security_delta=security_delta,
            blast_delta=blast_delta,
            sensitive_areas=sensitive_areas,
            quality_delta=quality_delta,
            change_map=change_map,
            validity_ok=validity_ok,
            broken_files=broken_files,
            verdict=verdict,
            risk_score=risk_score,
            summary=_summary(security_delta, quality_delta, False),
            hacker_review=hacker_review,
            ai_explanation="",
            ai_error="",
        )

        await _set_stage(state, "generating_explanation", "Generating explanation without changing verdict.")
        explanation, ai_error = await _generate_explanation(report)
        report["ai_explanation"] = explanation
        report["ai_error"] = ai_error

        current_head = await resolve_pull_request_head_sha(owner, repo, pr_number)
        if current_head and current_head != info.head_sha:
            report["stale"] = True
            report["current_head_sha"] = current_head
            report["summary"] = f"STALE - PR changed during analysis. This report is for {info.head_sha[:7]}, current HEAD is {current_head[:7]}."

        state["report"] = report
        state["status"] = "complete"
        state["stage"] = "complete"
        await _persist(state)
        print(
            f"[stage] PR_GUARD_COMPLETE project_id={project_id} pr={pr_number} verdict={verdict} "
            f"risk_score={risk_score} duration_ms={round((time.monotonic() - started) * 1000)}"
        )
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = f"PR Guard failed: {type(exc).__name__}"
        await _persist(state)
        print(f"[pr-guard] unhandled error project_id={project_id} pr={pr_number}: {exc}")
    finally:
        async with _guard:
            key = (project_id, pr_number)
            if _active_by_project_pr.get(key) == state.get("run_id"):
                _active_by_project_pr.pop(key, None)


async def start_pr_guard(project_id: str, owner_user_id: str, pr_number: int) -> dict:
    global _counter
    async with _guard:
        key = (project_id, pr_number)
        existing_id = _active_by_project_pr.get(key)
        if existing_id and existing_id in _active_runs:
            existing = _active_runs[existing_id]
            if existing["status"] not in _TERMINAL:
                return _public_state(existing)
        _counter += 1
        run_id = f"prguard-{project_id}-{pr_number}-{_counter}"
        state = {
            "run_id": run_id,
            "job_id": run_id,
            "project_id": project_id,
            "owner_user_id": owner_user_id,
            "pull_request_number": pr_number,
            "status": "queued",
            "stage": "queued",
            "message": "PR Guard queued.",
            "report": None,
            "error": None,
        }
        try:
            persisted_id = await create_pr_guard_run(project_id, owner_user_id, pr_number, _public_state(state))
            state["run_id"] = persisted_id
            state["job_id"] = persisted_id
            run_id = persisted_id
        except Exception as exc:
            print(f"[pr-guard] persistence unavailable, continuing in-memory only: {type(exc).__name__}: {exc}")
        _active_runs[run_id] = state
        _active_by_project_pr[key] = run_id
    asyncio.create_task(_run(project_id, owner_user_id, pr_number, state), name=f"pr-guard:{project_id}:{pr_number}")
    return _public_state(state)


async def get_pr_guard_status(project_id: str, owner_user_id: str, run_id: str) -> dict | None:
    state = _active_runs.get(run_id)
    if state and state.get("project_id") == project_id and state.get("owner_user_id") == owner_user_id:
        return _public_state(state)
    try:
        run = await get_owned_pr_guard_run(project_id, owner_user_id, run_id)
    except Exception as exc:
        print(f"[pr-guard] persisted status lookup failed project_id={project_id}: {type(exc).__name__}: {exc}")
        return None
    if run is None:
        return None
    if run.get("status") not in _TERMINAL:
        run["status"] = "failed"
        run["stage"] = "failed"
        run["error"] = "PR Guard was interrupted because the server restarted. Start a new run to continue."
    return run
