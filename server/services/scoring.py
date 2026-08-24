"""Phase 4 scoring engine: transparent, weighted, explainable.

Every deduction is tied to a real finding or a real heuristic check on the
stored project data — never a raw "the AI said 73". A category only ever
carries a numeric score when it was genuinely evaluated (a heuristic with a
real signal ran, or grounded findings targeting it exist); absence of a
finding is not proof of health when the dimension wasn't adequately checked,
so a category with no real signal is marked "not_evaluated" and excluded
from the weighted overall score rather than silently counted as 100.
"""

from services.standards import get_standard_by_id
from services.security_findings import authoritative_security_findings

# maps analyzer.py rule ids -> standards.py standard ids, so every deduction
# can cite the real external source it's grounded in.
RULE_TO_STANDARD = {
    "hardcoded_secret": "SEC-01",
    "sql_concat": "SEC-02",
    "dangerous_eval": "SEC-03",
    "subprocess_shell_true": "SEC-04",
    "tls_verification_disabled": "SEC-05",
    "unsafe_deserialization": "SEC-06",
    "empty_exception_handler": "CQ-01",
    "todo_marker": "CQ-02",
    "route_without_related_validation": "API-01",
    "large_route_handler": "ARCH-01",
    "possible_blocking_work": "PERF-01",
}

# The canonical, user-facing project-health dimensions, in the order they
# must always be displayed. Every response contains exactly these 7 keys,
# regardless of what was actually evaluated -- a dimension with nothing to
# show renders as "not_evaluated", never as a hidden key or a fake 100.
CATEGORY_ORDER = [
    "security",
    "code_quality",
    "architecture",
    "testing",
    "api_design",
    "performance",
    "production_readiness",
]

WEIGHTS = {
    "security": 0.20,
    "code_quality": 0.20,
    "architecture": 0.15,
    "testing": 0.15,
    "api_design": 0.10,
    "performance": 0.10,
    "production_readiness": 0.10,
}

SEVERITY_DEDUCTION = {
    "critical": 25,
    "high": 15,
    "medium": 8,
    "low": 3,
}

# Detailed finding categories (deterministic rules + the wider AI quality-
# review taxonomy) each route to exactly ONE of the 7 canonical project-
# health dimensions -- a single primary dimension per finding, never split
# across several, so nothing gets double-counted into the overall score.
# The finding's own, more specific category (e.g. "reliability", "privacy")
# is preserved and still shown as-is on the findings page; this mapping only
# governs which health-summary card a finding's score impact lands on.
FINDING_CATEGORY_MAP = {
    "security": "security",
    "privacy": "security",
    "best_practice": "code_quality",
    "correctness": "code_quality",
    "logic": "code_quality",
    "database": "code_quality",
    "data_integrity": "code_quality",
    "maintainability": "code_quality",
    "architecture": "architecture",
    "reliability": "architecture",
    "testing": "testing",
    "api_design": "api_design",
    "performance": "performance",
    "production_readiness": "production_readiness",
}


def _score_from_findings(findings: list[dict], target_category: str) -> tuple[int, list[dict]]:
    score = 100
    deductions = []
    for f in findings:
        if FINDING_CATEGORY_MAP.get(f.get("category")) != target_category:
            continue
        amount = SEVERITY_DEDUCTION.get(f.get("severity"), 3)
        score = max(0, score - amount)
        standard_id = RULE_TO_STANDARD.get(f.get("rule"))
        standard = get_standard_by_id(standard_id) if standard_id else None
        deductions.append(
            {
                "reason": f.get("message", ""),
                "amount": amount,
                "file": f.get("file"),
                "line": f.get("line"),
                "rule": f.get("rule"),
                "severity": f.get("severity"),
                "standard": {"id": standard["id"], "title": standard["title"], "evidenceSource": standard["evidenceSource"]}
                if standard
                else None,
            }
        )
    return score, deductions


def _finding_count(findings: list[dict], target_category: str) -> int:
    return sum(1 for f in findings if FINDING_CATEGORY_MAP.get(f.get("category")) == target_category)


def _category(score: int, weight: float, deductions: list[dict], status: str, finding_count: int) -> dict:
    return {
        "score": max(0, min(100, score)) if status != "not_evaluated" else None,
        "status": status,
        "weight": weight,
        "deductions": deductions,
        "finding_count": finding_count,
    }


def compute_score(project: dict) -> dict:
    findings = authoritative_security_findings(project)
    files = project.get("files", [])
    tests = project.get("tests", [])
    configs = project.get("configs", [])
    deployment_files = project.get("deploymentFiles", [])
    api_endpoints = project.get("apiEndpoints", [])
    coverage = project.get("ai_review_coverage") or {}
    # When the AI quality review didn't cover every eligible file, categories
    # that partly depend on it for signal (beyond pure deterministic/regex
    # checks) are genuinely evaluated but on incomplete coverage -- "partial",
    # not a full "evaluated", since a skipped file's issues in that dimension
    # simply weren't looked for.
    ai_partial = bool(coverage) and coverage.get("files_skipped", 0) > 0

    categories = {}

    # security / code_quality: deterministic rules run over every file
    # unconditionally, so these are always at least "evaluated" whenever the
    # project has files; AI quality review adds more signal on top (subject
    # to the same partial-coverage caveat as architecture/production below).
    for cat in ("security", "code_quality"):
        score, deductions = _score_from_findings(findings, cat)
        if not files:
            status = "not_evaluated"
        elif ai_partial:
            status = "partial"
        else:
            status = "evaluated"
        categories[cat] = _category(score, WEIGHTS[cat], deductions, status, len(deductions))

    # architecture: file-structure heuristic, PLUS architecture-category
    # findings (including "reliability", routed here).
    architecture_score, architecture_deductions = _score_from_findings(findings, "architecture")
    has_service_layer = any(
        "services" in f.get("path", "").replace("\\", "/").split("/") for f in files
    )
    if len(api_endpoints) >= 5 and not has_service_layer:
        architecture_score -= 15
        std = get_standard_by_id("ARCH-01")
        architecture_deductions.append(
            {
                "reason": "Multiple API endpoints detected but no service-layer files were found",
                "amount": 15,
                "standard": {"id": std["id"], "title": std["title"], "evidenceSource": std["evidenceSource"]},
            }
        )
    architecture_status = "not_evaluated" if not files else ("partial" if ai_partial else "evaluated")
    categories["architecture"] = _category(
        architecture_score, WEIGHTS["architecture"], architecture_deductions, architecture_status, len(architecture_deductions)
    )

    # api_design: only meaningfully evaluated when the project actually has
    # API endpoints to check -- a project with none isn't "perfectly
    # validated", it simply has nothing here to assess. This is the one
    # dimension that most often has a genuine not_evaluated state.
    api_deductions = []
    if not api_endpoints:
        api_status = "not_evaluated"
        api_score = 100  # unused when not_evaluated (score reported as None)
    else:
        api_score = 100
        if not any(
            token in (f.get("content") or "").lower()
            for f in files
            for token in ("pydantic", "joi", "zod", "express-validator", "validate")
        ):
            api_score -= 20
            std = get_standard_by_id("API-01")
            api_deductions.append(
                {
                    "reason": "API endpoints detected but no obvious boundary validation library or middleware was found",
                    "amount": 20,
                    "standard": {"id": std["id"], "title": std["title"], "evidenceSource": std["evidenceSource"]},
                }
            )
        finding_score, finding_deductions = _score_from_findings(findings, "api_design")
        api_score = min(api_score, finding_score)
        api_deductions.extend(finding_deductions)
        api_status = "partial" if ai_partial else "evaluated"
    categories["api_design"] = _category(api_score, WEIGHTS["api_design"], api_deductions, api_status, len(api_deductions))

    # performance: regex scan over every file's raw content -- always fully
    # evaluated when files exist, not AI-dependent, so no partial state.
    performance_score = 100
    performance_deductions = []
    blocking_markers = ("execsync", "readfilesync", "writefilesync", "sleep(", "time.sleep", "image.resize", "sharp(")
    for file_entry in files:
        content = (file_entry.get("content") or "").lower()
        if any(marker in content for marker in blocking_markers):
            performance_score -= 10
            std = get_standard_by_id("PERF-01")
            performance_deductions.append(
                {
                    "reason": "Potential blocking or expensive operation detected in source",
                    "amount": 10,
                    "file": file_entry.get("path"),
                    "standard": {"id": std["id"], "title": std["title"], "evidenceSource": std["evidenceSource"]},
                }
            )
            break
    finding_score, finding_deductions = _score_from_findings(findings, "performance")
    performance_score = min(performance_score, finding_score)
    performance_deductions.extend(finding_deductions)
    performance_status = "not_evaluated" if not files else "evaluated"
    categories["performance"] = _category(
        performance_score, WEIGHTS["performance"], performance_deductions, performance_status, len(performance_deductions)
    )

    # testing: file-presence heuristic -- always fully evaluated when files exist.
    testing_score = 100
    testing_deductions = []
    if files and not tests:
        testing_score -= 40
        std = get_standard_by_id("TEST-01")
        testing_deductions.append(
            {
                "reason": "No test files detected in project",
                "amount": 40,
                "standard": {"id": std["id"], "title": std["title"], "evidenceSource": std["evidenceSource"]},
            }
        )
    testing_status = "not_evaluated" if not files else "evaluated"
    categories["testing"] = _category(testing_score, WEIGHTS["testing"], testing_deductions, testing_status, len(testing_deductions))

    # production_readiness: file-presence heuristic (deployment config/
    # dependency manifest), PLUS production_readiness-category findings.
    prod_score, prod_deductions = _score_from_findings(findings, "production_readiness")
    if not deployment_files:
        prod_score -= 20
        std = get_standard_by_id("PROD-01")
        prod_deductions.append(
            {
                "reason": "No deployment configuration files found (e.g. Dockerfile)",
                "amount": 20,
                "standard": {"id": std["id"], "title": std["title"], "evidenceSource": std["evidenceSource"]},
            }
        )
    if not configs:
        prod_score -= 10
        prod_deductions.append(
            {
                "reason": "No dependency manifest found (e.g. requirements.txt, package.json)",
                "amount": 10,
                "standard": None,
            }
        )
    prod_status = "not_evaluated" if not files else ("partial" if ai_partial else "evaluated")
    categories["production_readiness"] = _category(
        prod_score, WEIGHTS["production_readiness"], prod_deductions, prod_status, len(prod_deductions)
    )

    # Overall score: weighted average over EVALUATED/PARTIAL categories only,
    # renormalized so excluded (not_evaluated) categories can't silently
    # count as perfect and can't silently drag the average down either --
    # they just don't participate.
    scored = [(cat, categories[cat]) for cat in CATEGORY_ORDER if categories[cat]["status"] != "not_evaluated"]
    evaluated_weight = sum(WEIGHTS[cat] for cat, _ in scored)
    overall = (
        sum(data["score"] * WEIGHTS[cat] for cat, data in scored) / evaluated_weight
        if evaluated_weight > 0
        else None
    )

    return {
        "overall_score": round(overall, 1) if overall is not None else None,
        "categories": {cat: categories[cat] for cat in CATEGORY_ORDER},
        "dimensions_evaluated": len(scored),
        "dimensions_total": len(CATEGORY_ORDER),
        "finding_count": len(findings),
    }
