from services.context_expansion import build_finding_context
from services.retrieval import retrieve_relevant_files
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


def test_retrieval_matches_short_literal_filename():
    project = {
        "files": [
            {
                "path": "db.py",
                "language": "python",
                "content": "def connect():\n    return sqlite3.connect('app.db')\n",
            },
            {"path": "config.py", "language": "python", "content": "DEBUG = True\n"},
        ],
        "functions": [{"file": "db.py", "name": "connect"}],
        "imports": [],
    }

    results = retrieve_relevant_files(project, "db.py")

    assert results
    assert results[0]["path"] == "db.py"


def test_retrieval_uses_findings_for_security_readiness_questions():
    project = {
        "files": [
            {"path": "config.py", "language": "python", "content": "SECRET = 'abc123'\n"},
            {"path": "db.py", "language": "python", "content": "query = 'SELECT ' + email\n"},
            {"path": "readme.md", "language": "other", "content": "production notes\n"},
        ],
        "findings": [
            {"file": "config.py", "severity": "critical"},
            {"file": "db.py", "severity": "high"},
        ],
    }

    results = retrieve_relevant_files(project, "Is this production ready from a security perspective?")

    assert [r["path"] for r in results[:2]] == ["config.py", "db.py"]


def test_retrieval_understands_database_intent():
    project = {
        "files": [
            {"path": "config.py", "language": "python", "content": "DATABASE_PASSWORD = 'secret'\n"},
            {
                "path": "db.py",
                "language": "python",
                "content": "import sqlite3\n\ndef get_user(email):\n    return sqlite3.connect('app.db').execute('SELECT * FROM users')\n",
            },
        ],
        "functions": [{"file": "db.py", "name": "get_user"}],
        "imports": [],
    }

    results = retrieve_relevant_files(project, "How is the database used?")

    assert results
    assert results[0]["path"] == "db.py"
