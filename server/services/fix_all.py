"""Fix All: sequential, safe auto-fix of every confirmed SAGE security finding.

Pure orchestration -- no new fixer. Reuses exactly the same pieces the
single-finding "Generate Fix" / "Apply Fix" endpoints in routers/projects.py
already use (services.reasoning_engine.generate_fix, services.patching,
knowledge retrieval, standards lookup) and the same canonical reanalysis
pipeline (_run_project_analysis) reanalyze_project already calls. Two of
those are imported lazily, inside functions, from routers.projects: that
module imports this one at load time to wire the endpoint, so importing it
back at module level here would be a circular import. By the time _run()
actually executes (well after both modules finished loading), the lazy
import is just a dict lookup.

Concurrency model matches services/analysis_jobs.py's own documented
choice: a single-process, in-memory, per-project job table is still the
source of truth while a run is live in this process. Unlike the very first
version of this module, run state (status/counts/source_revision -- never
the full per-finding results list, which stays in-memory/ephemeral) is
also mirrored to Mongo, so a crash/restart doesn't strand the frontend
polling a run that can now never complete; see get_fix_all_status_with_
recovery below, which mirrors analysis_jobs.get_analysis_job_with_recovery.
"""

import asyncio
import time
from ast import parse as _ast_parse
from datetime import datetime, timezone

from db.mongo import (
    create_fix_all_run,
    get_owned_fix_all_run,
    get_owned_project_metadata,
    hydrate_selected_files,
    update_fix_all_run,
    update_owned_project,
)
from knowledge.retrieval import build_finding_knowledge_query, retrieve_knowledge
from services.context_expansion import build_finding_context
from services.groq_client import GroqUnavailableError
from services.patching import PatchError, apply_structured_patch
from services.reasoning_engine import generate_fix
from services.retrieval import build_import_graph, get_related_files
from services.scoring import FINDING_CATEGORY_MAP, RULE_TO_STANDARD
from services.standards import get_standard_by_id, get_standards_for

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_active_runs: dict[str, dict] = {}
_guard = asyncio.Lock()
_job_counter = 0


def is_fix_all_running(project_id: str) -> bool:
    state = _active_runs.get(project_id)
    return bool(state and state["status"] == "running")


def get_fix_all_status(project_id: str) -> dict | None:
    return _active_runs.get(project_id)


# If Uvicorn crashes/restarts mid-run, Mongo is left holding a fix_all_runs
# doc stuck at status="running" forever -- _active_runs (this process's only
# record of which task actually owns it) is gone, and nothing will ever
# transition that doc again. A brand-new process has an empty _active_runs,
# so "not in the registry" is an unambiguous signal in this single-process
# deployment, not a heuristic. Mirrors analysis_jobs.STALE_JOB_GRACE_SECONDS.
FIX_ALL_STALE_RUN_GRACE_SECONDS = 30


def _run_age_seconds(run: dict) -> float | None:
    started = run.get("started_at")
    if started is None:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started).total_seconds()


def _run_doc_to_status(run: dict) -> dict:
    # Adapts a Mongo fix_all_runs doc to the same shape get_fix_all_status
    # returns from _active_runs, so routers/projects.py's response building
    # doesn't need to know which source it came from. results/report were
    # never persisted (ephemeral, see module docstring) -- lost across a
    # restart, same tradeoff analysis_jobs.py makes for its result payload.
    return {
        "job_id": run.get("_id", ""),
        "status": run.get("status", "failed"),
        "total": run.get("total", 0),
        "processed": run.get("processed", 0),
        "results": [],
        "report": None,
        "error": run.get("error"),
    }


async def get_fix_all_status_with_recovery(project_id: str, owner_user_id: str) -> dict | None:
    """Same contract as get_fix_all_status, but when this process has no
    in-memory record of the run (e.g. it started before a crash/restart),
    falls back to the Mongo-persisted run doc instead of reporting "no run
    found" for a run that actually existed -- and corrects an abandoned
    "running" doc to "failed" so polling can't hang forever. Mirrors
    services.analysis_jobs.get_analysis_job_with_recovery.

    Best-effort like every other Mongo touch point in this module: if Mongo
    isn't reachable/configured, that must degrade to "no persisted run
    found" (None), not break the status endpoint -- persistence is an
    enhancement over the in-memory path above, never a new failure mode.
    """
    state = _active_runs.get(project_id)
    if state is not None:
        return state  # this process's own live-or-finished record is authoritative

    try:
        run = await get_owned_fix_all_run(project_id, owner_user_id)
    except Exception as exc:
        print(f"[fix-all] run-state recovery lookup failed project_id={project_id}: {type(exc).__name__}: {exc}")
        return None
    if run is None or run.get("status") != "running":
        return _run_doc_to_status(run) if run else None

    age = _run_age_seconds(run)
    if age is not None and age < FIX_ALL_STALE_RUN_GRACE_SECONDS:
        return _run_doc_to_status(run)

    interrupted_at = datetime.now(timezone.utc)
    await _safe_update_fix_all_run(
        run["_id"], owner_user_id,
        {"status": "failed", "completed_at": interrupted_at, "error": "interrupted"},
    )
    run["status"] = "failed"
    run["error"] = "interrupted"
    return _run_doc_to_status(run)


async def _safe_update_fix_all_run(run_id: str | None, owner_user_id: str, updates: dict) -> None:
    # Best-effort: a Mongo hiccup while persisting run-state must never fail
    # or interrupt the actual fix -- that's the P0 guarantee and it does not
    # depend on this succeeding.
    if not run_id:
        return
    try:
        await update_fix_all_run(run_id, owner_user_id, updates)
    except Exception as exc:
        print(f"[fix-all] run-state persistence failed run_id={run_id}: {type(exc).__name__}: {exc}")


def request_stop(project_id: str) -> bool:
    state = _active_runs.get(project_id)
    if state is None or state["status"] != "running":
        return False
    state["stop_requested"] = True
    return True


async def start_fix_all(project_id: str, owner_user_id: str) -> dict:
    """Start (or return the already-running) Fix All job for this project.

    The guard makes "one write operation owns the project modification flow
    at a time" concrete for Fix All-vs-Fix All; the router additionally
    checks is_fix_all_running() before accepting a manual single-finding
    fix/apply request, covering Fix All-vs-manual-fix.
    """
    global _job_counter
    async with _guard:
        existing = _active_runs.get(project_id)
        if existing and existing["status"] == "running":
            return existing
        _job_counter += 1
        state = {
            "job_id": f"fixall-{project_id}-{_job_counter}",
            "status": "running",
            "stop_requested": False,
            "total": 0,
            "processed": 0,
            "results": [],
            "report": None,
            "error": None,
            "run_id": None,
        }
        _active_runs[project_id] = state
    try:
        state["run_id"] = await create_fix_all_run(project_id, owner_user_id)
    except Exception as exc:
        print(f"[fix-all] run-state persistence unavailable, continuing in-memory only: {type(exc).__name__}: {exc}")
    asyncio.create_task(_run(project_id, owner_user_id, state), name=f"fix-all:{project_id}")
    return state


def _sort_queue(findings: list[dict]) -> list[dict]:
    # Stable sort: severity primary key, finding_id secondary key so equal-
    # severity findings get a deterministic (not insertion-order-incidental,
    # not random) order across runs.
    return sorted(
        findings,
        key=lambda f: (_SEVERITY_ORDER.get(f.get("severity", "low"), 3), f.get("finding_id", "")),
    )


def _base_result(finding: dict) -> dict:
    return {
        "finding_id": finding.get("finding_id", ""),
        "title": finding.get("message") or finding.get("rule_id") or finding.get("rule", ""),
        "severity": finding.get("severity", "low"),
        "file": finding.get("file", ""),
        "status": "failed",
        "message": "",
    }


async def _process_one(project_id: str, owner_user_id: str, finding_snapshot: dict) -> dict:
    """Process exactly one finding against the CURRENT project state.

    Always re-fetches the project fresh -- this is what makes sequential
    processing safe: finding #2 sees whatever finding #1 actually persisted,
    never the state the queue was originally built from. Fetches metadata
    only (no GridFS reads) and hydrates just the target file plus its
    depth-1 import-graph neighbors -- the only files build_finding_context
    below actually looks at -- instead of every file in the project. This
    is what keeps a run findings x (1 file + a handful of neighbors)
    instead of findings x (entire repository).
    """
    result = _base_result(finding_snapshot)
    finding_id = finding_snapshot.get("finding_id")

    project = await get_owned_project_metadata(project_id, owner_user_id)
    if project is None:
        result["status"] = "failed"
        result["message"] = "Project no longer exists."
        return result

    target_path = finding_snapshot.get("file")
    # build_import_graph only reads file paths and the pre-extracted
    # project["imports"] list (see services/retrieval.py) -- no file
    # content needed to know which files are worth hydrating.
    graph = build_import_graph(project)
    related_paths = get_related_files(target_path, graph, depth=1)
    await hydrate_selected_files(project.get("files", []), paths=related_paths | {target_path})

    file_entry = next((f for f in project.get("files", []) if f.get("path") == target_path), None)
    if file_entry is None or file_entry.get("content") is None:
        result["status"] = "stale"
        result["message"] = "Target file no longer exists in the project."
        return result

    content = file_entry["content"]
    evidence = (finding_snapshot.get("evidence") or "").strip()
    if evidence and evidence not in content:
        # Not proof the underlying vulnerability class is gone (final
        # re-analysis settles that) -- but this exact evidence is, most
        # often because an earlier fix in this same run already touched or
        # removed the surrounding code. Forcing a patch against evidence
        # that no longer exists is exactly the "stale context" the spec
        # forbids, so treat it as resolved rather than fail it.
        result["status"] = "already_resolved"
        result["message"] = "This finding's evidence is no longer present in the file -- likely resolved by an earlier fix in this run."
        return result

    current_findings = project.get("security_findings", [])
    finding = next((f for f in current_findings if f.get("finding_id") == finding_id), None) or finding_snapshot

    try:
        context = build_finding_context(project, finding)
        # Related files were hydrated only to build the snippets already
        # captured in `context` above -- drop their content back out now so
        # the update_owned_project call below (and its deepcopy) only ever
        # carries the ONE file this finding actually changes, never a
        # multi-file or whole-repo payload.
        for f in project.get("files", []):
            if f.get("path") != target_path:
                f.pop("content", None)
        code_snippet = context["snippet"] or finding.get("evidence", "")
        language = context["language"]

        standard_id = RULE_TO_STANDARD.get(finding.get("rule"))
        matched_standards = [get_standard_by_id(standard_id)] if standard_id else []
        if not matched_standards:
            weight_category = FINDING_CATEGORY_MAP.get(finding.get("category"))
            if weight_category:
                matched_standards = get_standards_for(weight_category, language)[:2]

        weight_category = FINDING_CATEGORY_MAP.get(finding.get("category"))
        knowledge_query = build_finding_knowledge_query(finding, surrounding_context=code_snippet, detector_name=finding.get("rule"))
        knowledge = await retrieve_knowledge(
            knowledge_query,
            language=language,
            frameworks=project.get("project", {}).get("frameworks", []),
            category=weight_category,
            exact_rule_id=finding.get("rule"),
        )

        transform = await generate_fix(
            finding, code_snippet, language, matched_standards,
            related_files=context["related_files"], knowledge=knowledge,
        )
    except GroqUnavailableError as exc:
        result["status"] = "failed"
        result["message"] = f"AI fix generation unavailable: {exc}"
        return result
    except Exception as exc:
        result["status"] = "failed"
        result["message"] = f"Fix generation failed: {type(exc).__name__}"
        return result

    from routers.projects import _enrich_transform  # lazy: see module docstring

    transform = _enrich_transform(transform, finding, content)
    if not transform.can_apply:
        result["status"] = "failed"
        result["message"] = transform.apply_failure_reason or "Generated patch failed validation."
        return result

    try:
        applied = apply_structured_patch(
            content, transform.original_code, transform.fixed_code,
            expected_hash=transform.source_hash or None,
        )
    except PatchError as exc:
        result["status"] = "failed"
        result["message"] = f"Patch could not be applied: {exc}"
        return result

    new_content = applied.patched
    if not new_content.strip():
        result["status"] = "failed"
        result["message"] = "Rejected: patch produced an empty file."
        return result

    if file_entry.get("language") == "python":
        try:
            _ast_parse(new_content)
        except SyntaxError as exc:
            # Rollback is implicit: file_entry/content is a local dict never
            # persisted below when we return early here.
            result["status"] = "failed"
            result["message"] = f"Rejected: patch produced invalid Python ({exc.msg} at line {exc.lineno})."
            return result

    file_entry["content"] = new_content
    for f in project.get("security_findings", []):
        if f.get("finding_id") == finding_id:
            f["fix_state"] = "Applied"
            f["applied_patch"] = {
                "file": finding.get("file"),
                "original_code": transform.original_code,
                "fixed_code": transform.fixed_code,
                "diff": applied.diff,
            }
    project.setdefault("patches", [])
    project["patches"].append(
        {
            "finding_id": finding_id,
            "rule_id": finding.get("rule"),
            "file": finding.get("file"),
            "diff": applied.diff,
            "state": "Applied",
            "source": "fix_all",
        }
    )

    updated = await update_owned_project(
        project_id,
        owner_user_id,
        {
            "files": project["files"],
            "security_findings": project.get("security_findings", []),
            "patches": project["patches"],
            "source_revision": int(project.get("source_revision", 1)) + 1,
            "analysis_status": "stale",
            "compliance_score": None,
        },
        expected_source_revision=int(project.get("source_revision", 1)),
    )
    if not updated:
        result["status"] = "failed"
        result["message"] = "Project source changed concurrently; this fix was not applied."
        return result

    result["status"] = "fixed"
    result["message"] = "Patch applied successfully."
    return result


def _tally_counts(results: list[dict]) -> dict:
    counts = {"fixed": 0, "failed": 0, "skipped": 0, "already_resolved": 0, "stale": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


def _empty_report() -> dict:
    return {
        "status": "completed",
        "before_count": 0,
        "after_count": 0,
        "processed": 0,
        "fixed": 0,
        "failed": 0,
        "skipped": 0,
        "already_resolved": 0,
        "stopped_early": False,
        "verification_note": "No confirmed security findings to fix.",
        "results": [],
    }


async def _run(project_id: str, owner_user_id: str, state: dict) -> None:
    stage_start = time.monotonic()
    print(f"[stage] FIX_ALL_START project_id={project_id}")
    try:
        # Only security_findings/files metadata is needed to build the
        # queue -- no file content, so no hydration call at all.
        project = await get_owned_project_metadata(project_id, owner_user_id)
        if project is None:
            state["status"] = "failed"
            state["error"] = "Project not found."
            return

        queue = _sort_queue(list(project.get("security_findings", [])))
        if not queue:
            state["report"] = _empty_report()
            state["status"] = "completed"
            return

        state["total"] = len(queue)
        before_count = len(queue)
        await _safe_update_fix_all_run(
            state.get("run_id"), owner_user_id,
            {"total": state["total"], "source_revision": project.get("source_revision")},
        )

        for finding in queue:
            if state["stop_requested"]:
                break
            outcome = await _process_one(project_id, owner_user_id, finding)
            state["results"].append(outcome)
            state["processed"] += 1
            print(
                f"[stage] FIX_ALL_FINDING project_id={project_id} finding_id={finding.get('finding_id')} "
                f"status={outcome.get('status')} processed={state['processed']}/{state['total']}"
            )
            tally = _tally_counts(state["results"])
            await _safe_update_fix_all_run(
                state.get("run_id"), owner_user_id,
                {
                    "processed": state["processed"],
                    "fixed": tally.get("fixed", 0),
                    "failed": tally.get("failed", 0) + tally.get("stale", 0),
                    "skipped": tally.get("skipped", 0),
                },
            )

        stopped_early = state["stop_requested"]
        if stopped_early:
            for remaining in queue[state["processed"]:]:
                result = _base_result(remaining)
                result["status"] = "skipped"
                result["message"] = "Not processed -- Fix All was stopped before reaching this finding."
                state["results"].append(result)

        # Mandatory final truth: never trust "patch applied" as proof a
        # vulnerability is gone. A fresh deterministic re-analysis is the
        # only thing allowed to say a finding is actually resolved.
        from routers.projects import _run_project_analysis  # lazy: see module docstring

        after_count = before_count
        reanalysis_ok = True
        try:
            await _run_project_analysis(project_id, owner_user_id)
            # Only the post-reanalysis finding count is needed here -- no
            # file content, so metadata-only, no hydration.
            after_project = await get_owned_project_metadata(project_id, owner_user_id)
            after_count = len(after_project.get("security_findings", [])) if after_project else before_count
        except Exception as exc:
            reanalysis_ok = False
            print(f"[fix-all] final reanalysis failed project_id={project_id}: {type(exc).__name__}: {exc}")

        counts = _tally_counts(state["results"])

        state["report"] = {
            "status": "completed" if reanalysis_ok else "completed_verification_failed",
            "before_count": before_count,
            "after_count": after_count,
            "processed": state["processed"],
            "fixed": counts.get("fixed", 0),
            "failed": counts.get("failed", 0) + counts.get("stale", 0),
            "skipped": counts.get("skipped", 0),
            "already_resolved": counts.get("already_resolved", 0),
            "stopped_early": stopped_early,
            "verification_note": (
                "Fixes were applied, but final verification could not complete."
                if not reanalysis_ok
                else "Post-fix status confirmed by a fresh deterministic re-analysis."
            ),
            "results": state["results"],
        }
        state["status"] = "completed"
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = f"Fix All failed: {type(exc).__name__}"
        print(f"[fix-all] unhandled error project_id={project_id}: {exc}")
    finally:
        # Release the concurrency guard regardless of outcome -- a crashed
        # run must not permanently lock the project out of Fix All / manual
        # fixes.
        if state["status"] == "running":
            state["status"] = "failed"
            state["error"] = state.get("error") or "Fix All ended unexpectedly."

        final_update = {
            "status": state["status"],
            "error": state.get("error"),
            "processed": state.get("processed", 0),
            "completed_at": datetime.now(timezone.utc),
        }
        report = state.get("report")
        if report:
            final_update["fixed"] = report.get("fixed", 0)
            final_update["failed"] = report.get("failed", 0)
            final_update["skipped"] = report.get("skipped", 0)
        await _safe_update_fix_all_run(state.get("run_id"), owner_user_id, final_update)
        print(
            f"[stage] FIX_ALL_COMPLETE project_id={project_id} status={state['status']} "
            f"processed={state.get('processed', 0)} duration_ms={round((time.monotonic() - stage_start) * 1000)}"
        )
