"""Phase 4 scoring engine: transparent, weighted, explainable.

Every deduction is tied to a real finding or a real heuristic check on the
stored project data — never a raw "the AI said 73". Categories with no
deterministic signal yet stay at 100 and say so explicitly in the breakdown,
rather than faking a number.
"""

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
FINDING_CATEGORY_MAP = {
    "security": "security",
    "best_practice": "code_quality",
}


def _score_from_findings(findings: list[dict], target_category: str) -> tuple[int, list[dict]]:
    score = 100
    deductions = []
    for f in findings:
        if FINDING_CATEGORY_MAP.get(f.get("category")) != target_category:
            continue
        amount = SEVERITY_DEDUCTION.get(f.get("severity"), 3)
        score = max(0, score - amount)
        deductions.append(
            {
                "reason": f.get("message", ""),
                "amount": amount,
                "file": f.get("file"),
                "line": f.get("line"),
                "rule": f.get("rule"),
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

    # testing: heuristic — no test files detected in a non-empty project is a real signal
    testing_score = 100
    testing_deductions = []
    if files and not tests:
        testing_score -= 40
        testing_deductions.append(
            {"reason": "No test files detected in project", "amount": 40}
        )
    categories["testing"] = {
        "score": max(0, testing_score),
        "weight": WEIGHTS["testing"],
        "deductions": testing_deductions,
    }

    # production_readiness: heuristic — missing deployment config / dependency manifest
    prod_score = 100
    prod_deductions = []
    if not deployment_files:
        prod_score -= 20
        prod_deductions.append(
            {"reason": "No deployment configuration files found (e.g. Dockerfile)", "amount": 20}
        )
    if not configs:
        prod_score -= 10
        prod_deductions.append(
            {"reason": "No dependency manifest found (e.g. requirements.txt, package.json)", "amount": 10}
        )
    categories["production_readiness"] = {
        "score": max(0, prod_score),
        "weight": WEIGHTS["production_readiness"],
        "deductions": prod_deductions,
    }

    # No deterministic signal yet for these — stay at 100, say so explicitly rather
    # than faking a number. Honest > impressive.
    for cat in ("architecture", "api_design", "performance"):
        categories[cat] = {
            "score": 100,
            "weight": WEIGHTS[cat],
            "deductions": [],
            "note": "No deterministic checks implemented for this category yet — score is a placeholder, not a real assessment.",
        }

    overall = sum(categories[cat]["score"] * WEIGHTS[cat] for cat in WEIGHTS)

    return {
        "overall_score": round(overall, 1),
        "categories": categories,
    }
