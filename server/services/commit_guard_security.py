"""Commit Guard: security-delta engine.

Classifies a commit's closed-world security findings as NEW / RESOLVED /
PERSISTING by comparing the BASE and HEAD snapshots through the exact same
pipeline SAGE already uses everywhere (analyzer.analyze_project ->
security_rules.to_closed_world_findings). No separate/weaker check, no AI
involvement -- pure deterministic comparison of two already-fetched
snapshots.
"""

from __future__ import annotations

from services.analyzer import analyze_project
from services.git_history import snapshot_to_project
from services.security_rules import to_closed_world_findings


def _normalized_evidence(finding: dict) -> str:
    # Mirrors routers/projects.py's _finding_id evidence normalization
    # exactly: whitespace-collapsed, lowercased. Reused here rather than
    # imported since that function also folds in file/line (which the
    # signature below must NOT do).
    return " ".join((finding.get("evidence") or "").split()).lower()


def _signature(finding: dict, renamed_to_new: dict[str, str]) -> tuple[str, str, str]:
    """(rule_id, HEAD-normalized file path, normalized evidence). Deliberately
    excludes line number so a finding whose evidence merely shifted lines
    (or whose file was renamed) still matches across BASE/HEAD."""
    file = finding.get("file") or ""
    file = renamed_to_new.get(file, file)
    return (finding.get("rule_id") or "", file, _normalized_evidence(finding))


async def compute_security_delta(
    base_snapshot: dict[str, str],
    head_snapshot: dict[str, str],
    renamed_paths: dict[str, str] | None = None,
) -> dict:
    """Pure/offline: base_snapshot and head_snapshot are already-fetched
    {path: content} dicts (from git_history.fetch_snapshot). renamed_paths
    is {new_path: old_path} for files GitHub reported as renamed."""
    renamed_paths = renamed_paths or {}
    # We sign every finding by its HEAD-side path. A BASE finding whose file
    # is a rename's old_path needs translating to new_path; renamed_paths is
    # already keyed {new: old}, so invert it for old->new lookup.
    old_to_new = {old: new for new, old in renamed_paths.items()}

    base_analyzed = analyze_project(snapshot_to_project(base_snapshot))
    head_analyzed = analyze_project(snapshot_to_project(head_snapshot))
    base_findings = to_closed_world_findings(base_analyzed.get("findings", []))
    head_findings = to_closed_world_findings(head_analyzed.get("findings", []))

    base_by_sig = {_signature(f, old_to_new): f for f in base_findings}
    head_by_sig = {_signature(f, {}): f for f in head_findings}

    new_sigs = head_by_sig.keys() - base_by_sig.keys()
    resolved_sigs = base_by_sig.keys() - head_by_sig.keys()
    persisting_sigs = head_by_sig.keys() & base_by_sig.keys()

    def _tag(finding: dict, sig: tuple[str, str, str]) -> dict:
        out = dict(finding)
        out["signature"] = "\x1f".join(sig)
        return out

    return {
        "base_findings": base_findings,
        "head_findings": head_findings,
        "new": [_tag(head_by_sig[s], s) for s in new_sigs],
        "resolved": [_tag(base_by_sig[s], s) for s in resolved_sigs],
        "persisting": [_tag(head_by_sig[s], s) for s in persisting_sigs],
    }
