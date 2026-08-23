import pytest

from routers import projects
from services import blast_radius
from services.blast_radius import build_blast_radius
from services.groq_client import GroqUnavailableError


def _fake_hydrate(monkeypatch, content_by_path=None):
    content_by_path = content_by_path or {}
    calls = []

    async def fake(files, paths=None, max_concurrency=12):
        calls.append(None if paths is None else set(paths))
        for entry in files:
            if entry.get("content") is not None:
                continue
            if paths is not None and entry.get("path") not in paths:
                continue
            if entry.get("path") in content_by_path:
                entry["content"] = content_by_path[entry["path"]]

    monkeypatch.setattr(blast_radius, "hydrate_selected_files", fake)
    return calls


@pytest.fixture(autouse=True)
def hydrate_calls(monkeypatch):
    return _fake_hydrate(monkeypatch)


@pytest.mark.asyncio
async def test_simple_python_app_builds_real_graph_and_ignores_readme(hydrate_calls):
    project = {
        "files": [
            {"path": "main.py", "language": "python", "content": "from services import run\n\nrun()\n"},
            {"path": "services.py", "language": "python", "content": "from models import User\n\ndef run():\n    return User()\n"},
            {"path": "models.py", "language": "python", "content": "class User:\n    pass\n"},
            {"path": "README.md", "language": "other", "content": "main.py imports fake_admin.py\n"},
        ],
        "findings": [],
    }

    report = await build_blast_radius(project, include_ai=False)

    assert report["summary"]["components_analyzed"] == 3
    assert {c["id"] for c in report["components"]} == {"main.py", "services.py", "models.py"}
    assert "README.md" not in {c["id"] for c in report["components"]}
    assert {(e["source"], e["target"], e["relation"]) for e in report["edges"]} == {
        ("main.py", "services.py", "imports"),
        ("services.py", "models.py", "imports"),
    }
    assert hydrate_calls == [{"main.py", "services.py", "models.py"}]


@pytest.mark.asyncio
async def test_auth_dependency_ranks_higher_than_independent_utility():
    project = {
        "files": [
            {
                "path": "auth.py",
                "language": "python",
                "content": "SECRET='x'\ndef verify(token):\n    return token == SECRET\n",
            },
            {
                "path": "users.py",
                "language": "python",
                "content": "from auth import verify\n\ndef user(token):\n    return verify(token)\n",
            },
            {
                "path": "admin.py",
                "language": "python",
                "content": "from auth import verify\nfrom database import execute\n\ndef admin(token):\n    return verify(token) and execute('select 1')\n",
            },
            {
                "path": "reports.py",
                "language": "python",
                "content": "from auth import verify\nfrom database import execute\n\ndef report(token):\n    return execute('select * from reports') if verify(token) else None\n",
            },
            {"path": "database.py", "language": "python", "content": "def execute(sql):\n    return sql\n"},
            {"path": "formatting.py", "language": "python", "content": "def title(s):\n    return s.title()\n"},
        ],
        "findings": [{"file": "auth.py", "rule": "SEC-HARDCODED-SECRET", "line": 1, "severity": "high"}],
    }

    report = await build_blast_radius(project, include_ai=False)
    by_id = {c["id"]: c for c in report["components"]}

    assert by_id["auth.py"]["score"] > by_id["formatting.py"]["score"]
    assert by_id["auth.py"]["level"] in {"medium", "high", "critical"}
    assert by_id["auth.py"]["direct_dependents"] == 3
    assert "database.py" in by_id["auth.py"]["affected_components"]
    assert by_id["formatting.py"]["level"] == "low"


@pytest.mark.asyncio
async def test_missing_groq_keeps_graph_and_scores(monkeypatch):
    async def fail_call_groq(messages, temperature=0.0):
        raise GroqUnavailableError("no keys")

    monkeypatch.setattr(blast_radius, "call_groq", fail_call_groq)
    project = {
        "files": [
            {"path": "main.py", "language": "python", "content": "from db import get\n\ndef route():\n    return get()\n"},
            {"path": "db.py", "language": "python", "content": "import sqlite3\n\ndef get():\n    return sqlite3.connect('x')\n"},
        ],
        "findings": [],
    }

    report = await build_blast_radius(project, include_ai=True)

    assert report["components"]
    assert report["edges"]
    assert report["ai"]["used"] is False
    assert report["ai"]["error"] == "no keys"
    assert all(component["explanation"] for component in report["components"])


@pytest.mark.asyncio
async def test_large_repo_hydrates_bounded_python_selection(monkeypatch):
    files = []
    content_by_path = {}
    for i in range(blast_radius.MAX_PYTHON_FILES + 25):
        path = f"pkg/module_{i}.py"
        files.append({"path": path, "language": "python", "content_ref": f"ref-{i}", "size": i})
        content_by_path[path] = f"def f_{i}():\n    return {i}\n"
    project = {"files": files, "findings": []}

    calls = _fake_hydrate(monkeypatch, content_by_path)
    report = await build_blast_radius(project, include_ai=False)

    assert len(calls) == 1
    assert calls[0] is not None
    assert len(calls[0]) == blast_radius.MAX_PYTHON_FILES
    assert report["summary"]["analysis_capped"] is True
    assert report["summary"]["python_files_considered"] == blast_radius.MAX_PYTHON_FILES + 25


@pytest.mark.asyncio
async def test_blast_radius_route_reuses_owned_project(monkeypatch):
    project = {"files": [{"path": "main.py", "language": "python", "content": "x=1\n"}], "findings": []}
    seen = {}

    async def fake_get_owned_project_metadata(project_id, owner_user_id):
        seen["project_id"] = project_id
        seen["owner_user_id"] = owner_user_id
        return project

    async def fake_build_blast_radius(received_project):
        assert received_project is project
        return {"summary": {"components_analyzed": 1}, "components": [], "edges": [], "ai": {"used": False}}

    monkeypatch.setattr(projects, "get_owned_project_metadata", fake_get_owned_project_metadata)
    monkeypatch.setattr(projects, "build_blast_radius", fake_build_blast_radius)

    response = await projects.blast_radius_report("project-1", current_user={"_id": "demo-user"})

    assert response["summary"]["components_analyzed"] == 1
    assert seen == {"project_id": "project-1", "owner_user_id": "demo-user"}
