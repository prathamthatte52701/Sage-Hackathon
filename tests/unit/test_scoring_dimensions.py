"""Scoring honesty: 7 canonical project-health dimensions always present,
never silently 100 when not evaluated, findings map to exactly one
dimension, overall score is coverage-aware (renormalized over evaluated
dimensions only)."""

from services.scoring import CATEGORY_ORDER, FINDING_CATEGORY_MAP, WEIGHTS, compute_score


def test_all_seven_canonical_dimensions_always_present_in_order():
    project = {"files": [], "findings": [], "tests": [], "configs": [], "deploymentFiles": [], "apiEndpoints": []}
    score = compute_score(project)
    assert list(score["categories"].keys()) == CATEGORY_ORDER
    assert set(WEIGHTS.keys()) == set(CATEGORY_ORDER)


def test_empty_project_is_not_evaluated_not_silently_perfect():
    project = {"files": [], "findings": [], "tests": [], "configs": [], "deploymentFiles": [], "apiEndpoints": []}
    score = compute_score(project)
    for cat, data in score["categories"].items():
        assert data["status"] == "not_evaluated", f"{cat} should be not_evaluated for an empty project"
        assert data["score"] is None, f"{cat} should report score=None, not a fake 100, when not evaluated"
    assert score["dimensions_evaluated"] == 0


def test_api_design_not_evaluated_when_no_endpoints_exist():
    project = {
        "files": [{"path": "utils.js", "language": "javascript", "content": "function add(a, b) { return a + b; }"}],
        "findings": [],
        "tests": ["utils.test.js"],
        "configs": ["package.json"],
        "deploymentFiles": ["Dockerfile"],
        "apiEndpoints": [],  # no routes in this project at all
    }
    score = compute_score(project)
    assert score["categories"]["api_design"]["status"] == "not_evaluated"
    assert score["categories"]["api_design"]["score"] is None


def test_api_design_evaluated_when_endpoints_exist():
    project = {
        "files": [{"path": "app.js", "language": "javascript", "content": "router.post('/x', validate, h)"}],
        "findings": [],
        "tests": ["app.test.js"],
        "configs": ["package.json"],
        "deploymentFiles": ["Dockerfile"],
        "apiEndpoints": [{"file": "app.js", "method": "POST", "path": "/x"}],
    }
    score = compute_score(project)
    assert score["categories"]["api_design"]["status"] == "evaluated"
    assert score["categories"]["api_design"]["score"] is not None


def test_overall_score_excludes_not_evaluated_dimensions_from_weighting():
    # A project with real files but zero API endpoints -- api_design must be
    # excluded from the weighted average rather than silently contributing
    # a perfect 100 that inflates the overall score.
    project = {
        "files": [{"path": "utils.js", "language": "javascript", "content": "eval(userInput)"}],
        "findings": [{"file": "utils.js", "line": 1, "rule": "dangerous_eval", "severity": "critical", "category": "security", "message": "eval on untrusted input"}],
        "tests": [],
        "configs": [],
        "deploymentFiles": [],
        "apiEndpoints": [],
    }
    score = compute_score(project)
    assert score["categories"]["api_design"]["status"] == "not_evaluated"
    assert score["overall_score"] is not None
    # security got hit hard (critical finding, -25) -- overall should reflect
    # that, not be diluted by a phantom perfect api_design score
    assert score["overall_score"] < 90


def test_each_finding_maps_to_exactly_one_canonical_dimension():
    detailed_categories = [
        "security", "privacy", "best_practice", "correctness", "logic",
        "database", "data_integrity", "maintainability", "architecture",
        "reliability", "testing", "api_design", "performance", "production_readiness",
    ]
    for cat in detailed_categories:
        mapped = FINDING_CATEGORY_MAP.get(cat)
        assert mapped in CATEGORY_ORDER, f"{cat} must map to exactly one canonical dimension, got {mapped}"


def test_reliability_and_privacy_findings_affect_their_mapped_dimension():
    project = {
        "files": [{"path": "auth.js", "language": "javascript", "content": "let cachedUser = null;"}],
        "findings": [
            {"file": "auth.js", "line": 1, "rule": "", "severity": "high", "category": "reliability", "message": "process-local cache"},
            {"file": "auth.js", "line": 2, "rule": "", "severity": "high", "category": "privacy", "message": "PII sent to third party"},
        ],
        "tests": ["auth.test.js"],
        "configs": ["package.json"],
        "deploymentFiles": ["Dockerfile"],
        "apiEndpoints": [],
    }
    score = compute_score(project)
    # reliability -> architecture, privacy -> security (per FINDING_CATEGORY_MAP)
    assert score["categories"]["architecture"]["score"] < 100
    assert score["categories"]["security"]["score"] < 100
    assert score["categories"]["architecture"]["finding_count"] == 1
    assert score["categories"]["security"]["finding_count"] == 1


def test_finding_count_reported_per_dimension():
    project = {
        "files": [{"path": "app.js", "language": "javascript", "content": "eval(x)"}],
        "findings": [
            {"file": "app.js", "line": 1, "rule": "dangerous_eval", "severity": "critical", "category": "security", "message": "eval"},
            {"file": "app.js", "line": 2, "rule": "dangerous_eval", "severity": "high", "category": "security", "message": "eval 2"},
        ],
        "tests": [],
        "configs": [],
        "deploymentFiles": [],
        "apiEndpoints": [],
    }
    score = compute_score(project)
    assert score["categories"]["security"]["finding_count"] == 2
