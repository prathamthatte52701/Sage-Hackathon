"""Phase 4 scoring engine: transparent, weighted, explainable.

Every deduction is tied to a real finding or a real heuristic check on the
stored project data — never a raw "the AI said 73". Categories with no
deterministic signal yet stay at 100 and say so explicitly in the breakdown,
rather than faking a number.
"""

from services.standards import get_standard_by_id

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

# analyzer.py's finding "category" values map onto these weight categories.
# The AI quality review (services/project_review.py) can also produce
# reliability/database/data_integrity/privacy/maintainability/correctness/
# production_readiness findings (Issue schema, Phase 7) -- without an entry
# here those real, grounded findings would be shown to the user but silently
# not affect the score at all. Routed to the closest existing weighted
# bucket rather than adding new WEIGHTS categories (smaller correction).
FINDING_CATEGORY_MAP = {
    "security": "security",
    "best_practice": "code_quality",
    "api_design": "api_design",
    "architecture": "architecture",
    "performance": "performance",
    "correctness": "code_quality",
    "logic": "code_quality",
    "reliability": "architecture",
    "database": "code_quality",
    "data_integrity": "code_quality",
    "privacy": "security",
    "maintainability": "code_quality",
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
                "standard": {"id": standard["id"], "title": standard["title"], "evidenceSource": standard["evidenceSource"]}
                if standard
                else None,
            }
        )
    return score, deductions


def compute_score(project: dict) -> dict:
    findings = project.get("findings", [])
    files = project.get("files", [])
    tests = project.get("tests", [])
    configs = project.get("configs", [])
    deployment_files = project.get("deploymentFiles", [])

    categories = {}

    for cat in ("security", "code_quality"):
        score, deductions = _score_from_findings(findings, cat)
        categories[cat] = {"score": score, "weight": WEIGHTS[cat], "deductions": deductions}

    # architecture: file-structure heuristic below, PLUS any architecture-
    # category findings (including "reliability", routed here by
    # FINDING_CATEGORY_MAP) from AI quality review.
    architecture_score, architecture_deductions = _score_from_findings(findings, "architecture")
    has_service_layer = any(
        "services" in f.get("path", "").replace("\\", "/").split("/") for f in files
    )
    if len(project.get("apiEndpoints", [])) >= 5 and not has_service_layer:
        architecture_score -= 15
        std = get_standard_by_id("ARCH-01")
        architecture_deductions.append(
            {
                "reason": "Multiple API endpoints detected but no service-layer files were found",
                "amount": 15,
                "standard": {"id": std["id"], "title": std["title"], "evidenceSource": std["evidenceSource"]},
            }
        )
    categories["architecture"] = {
        "score": max(0, architecture_score),
        "weight": WEIGHTS["architecture"],
        "deductions": architecture_deductions,
    }

    api_score = 100
    api_deductions = []
    if project.get("apiEndpoints", []) and not any(
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
    categories["api_design"] = {
        "score": max(0, api_score),
        "weight": WEIGHTS["api_design"],
        "deductions": api_deductions,
    }

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
    categories["performance"] = {
        "score": max(0, performance_score),
        "weight": WEIGHTS["performance"],
        "deductions": performance_deductions,
    }

    # testing: heuristic — no test files detected in a non-empty project is a real signal
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
    categories["testing"] = {
        "score": max(0, testing_score),
        "weight": WEIGHTS["testing"],
        "deductions": testing_deductions,
    }

    # production_readiness: file-presence heuristic below, PLUS any
    # production_readiness-category findings from AI quality review --
    # combined so a finding-based signal isn't invisible to this category.
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
    categories["production_readiness"] = {
        "score": max(0, prod_score),
        "weight": WEIGHTS["production_readiness"],
        "deductions": prod_deductions,
    }

    overall = sum(categories[cat]["score"] * WEIGHTS[cat] for cat in WEIGHTS)

    return {
        "overall_score": round(overall, 1),
        "categories": categories,
    }
