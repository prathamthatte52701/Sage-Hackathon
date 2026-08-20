from services.analyzer import analyze_project
from services.analyzers.rules import run_rules


def test_hardcoded_secret_true_positive():
    findings = run_rules("app.py", "python", "API_KEY = 'abcdef12345'\n")
    assert any(f["rule"] == "hardcoded_secret" for f in findings)


def test_hardcoded_secret_ignores_comment_and_fake_example():
    content = """
# API_KEY = 'abcdef12345'
example_secret = 'abcdef12345'
"""
    findings = run_rules("README.py", "python", content)
    assert not any(f["rule"] == "hardcoded_secret" for f in findings)


def test_javascript_route_and_function_extraction():
    project = {
        "files": [
            {
                "path": "routes/users.js",
                "language": "javascript",
                "content": "const createUser = async (req, res) => res.send('ok');\nrouter.post('/users', createUser)",
            }
        ],
        "imports": [],
        "functions": [],
        "classes": [],
        "apiEndpoints": [],
        "tests": [],
        "configs": [],
        "deploymentFiles": [],
        "findings": [],
        "warnings": [],
    }
    analyzed = analyze_project(project)
    assert {"file": "routes/users.js", "name": "createUser"} in analyzed["functions"]
    assert analyzed["apiEndpoints"][0]["method"] == "POST"
    assert analyzed["apiEndpoints"][0]["path"] == "/users"


def test_python_fastapi_route_extraction():
    project = {
        "files": [
            {
                "path": "main.py",
                "language": "python",
                "content": "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health():\n    return {'ok': True}\n",
            }
        ],
        "imports": [],
        "functions": [],
        "classes": [],
        "apiEndpoints": [],
        "tests": [],
        "configs": [],
        "deploymentFiles": [],
        "findings": [],
        "warnings": [],
    }
    analyzed = analyze_project(project)
    assert analyzed["apiEndpoints"][0]["method"] == "GET"
    assert analyzed["apiEndpoints"][0]["path"] == "/health"
    assert analyzed["apiEndpoints"][0]["handler"] == "health"
