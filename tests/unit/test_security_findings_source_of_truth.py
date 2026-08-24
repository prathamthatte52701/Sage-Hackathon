import pytest

from models.schemas import FindingReasonRequest, FindingReasoning, FindingTransform
from routers import projects


def _divergent_project():
    security_finding = {
        "finding_id": "real",
        "file": "app.py",
        "line": 1,
        "rule": "hardcoded_secret",
        "rule_id": "SEC-HARDCODED-SECRET",
        "severity": "critical",
        "category": "security",
        "message": "real authoritative finding",
        "evidence": "API_KEY = 'real-secret-value-123'",
    }
    stale_finding = {
        "finding_id": "stale",
        "file": "other.py",
        "line": 9,
        "rule": "dangerous_eval",
        "rule_id": "SEC-EVAL-EXEC",
        "severity": "critical",
        "category": "security",
        "message": "stale legacy finding",
        "evidence": "eval(user_input)",
    }
    return {
        "_id": "p1",
        "project": {"name": "demo", "languages": ["python"]},
        "files": [{"path": "app.py", "language": "python", "content": "API_KEY = 'real-secret-value-123'\n"}],
        "security_findings": [security_finding],
        "findings": [stale_finding],
    }


@pytest.mark.asyncio
async def test_reason_uses_security_findings_over_stale_legacy_findings(monkeypatch):
    project = _divergent_project()
    seen = {}

    async def fake_get_owned_project(_id, _owner_user_id):
        return project

    async def fake_retrieve_knowledge(*_args, **_kwargs):
        return {"records": []}

    async def fake_confirm(finding, *_args, **_kwargs):
        seen["finding"] = finding
        return FindingReasoning(reasoning="ok", confidence=0.9)

    async def fake_update_owned_finding(*_args, **_kwargs):
        return True

    monkeypatch.setattr(projects, "get_owned_project", fake_get_owned_project)
    monkeypatch.setattr(projects, "retrieve_knowledge", fake_retrieve_knowledge)
    monkeypatch.setattr(projects, "confirm_and_explain_finding", fake_confirm)
    monkeypatch.setattr(projects, "update_owned_finding", fake_update_owned_finding)

    result = await projects.reason_about_finding(
        "p1", FindingReasonRequest(finding_id="real"), current_user={"_id": "test-user"}
    )

    assert result.reasoning == "ok"
    assert seen["finding"]["finding_id"] == "real"


@pytest.mark.asyncio
async def test_transform_uses_security_findings_over_stale_legacy_findings(monkeypatch):
    project = _divergent_project()
    seen = {}

    async def fake_get_owned_project(_id, _owner_user_id):
        return project

    async def fake_retrieve_knowledge(*_args, **_kwargs):
        return {"records": []}

    async def fake_generate_fix(finding, *_args, **_kwargs):
        seen["finding"] = finding
        return FindingTransform(
            original_snippet="API_KEY = 'real-secret-value-123'",
            proposed_fix="API_KEY = os.environ['API_KEY']",
            explanation="Move the secret to the environment.",
            confidence=0.95,
        )

    async def fake_update_owned_finding(*_args, **_kwargs):
        return True

    monkeypatch.setattr(projects, "get_owned_project", fake_get_owned_project)
    monkeypatch.setattr(projects, "retrieve_knowledge", fake_retrieve_knowledge)
    monkeypatch.setattr(projects, "generate_fix", fake_generate_fix)
    monkeypatch.setattr(projects, "update_owned_finding", fake_update_owned_finding)

    result = await projects.transform_finding(
        "p1", FindingReasonRequest(finding_id="real"), current_user={"_id": "test-user"}
    )

    assert result.finding_id == "real"
    assert result.file == "app.py"
    assert seen["finding"]["finding_id"] == "real"
