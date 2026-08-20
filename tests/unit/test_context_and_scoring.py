from services.context_expansion import build_finding_context
from services.scoring import compute_score


def test_context_expands_to_imported_service():
    project = {
        "files": [
            {"path": "routes/user.js", "language": "javascript", "content": "const svc = require('../services/user')\neval(req.body.x)"},
            {"path": "services/user.js", "language": "javascript", "content": "module.exports = { create() {} }"},
        ],
        "imports": [{"file": "routes/user.js", "module": "../services/user"}],
    }
    finding = {"file": "routes/user.js", "line": 2, "evidence": "eval("}
    context = build_finding_context(project, finding)
    assert context["related_files"][0]["path"] == "services/user.js"


def test_scoring_uses_measured_api_and_performance_signals():
    project = {
        "files": [
            {"path": "app.js", "language": "javascript", "content": "router.post('/x', h)\nrequire('fs').readFileSync('x')"},
        ],
        "findings": [],
        "tests": [],
        "configs": [],
        "deploymentFiles": [],
        "apiEndpoints": [{"file": "app.js", "method": "POST", "path": "/x"}],
    }
    score = compute_score(project)
    assert score["categories"]["api_design"]["score"] < 100
    assert score["categories"]["performance"]["score"] < 100
    assert score["categories"]["testing"]["score"] < 100
