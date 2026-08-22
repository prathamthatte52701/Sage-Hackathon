"""Phase 5/14/16 CRITICAL security test: User B must never be able to read,
analyze, fix, reanalyze, or download User A's project.

Uses a tiny in-memory fake in place of db.mongo's project functions so this
runs without a live MongoDB -- it verifies the ROUTER's ownership-check
logic (every project route calls get_owned_project/update_owned_project,
which filter by {_id, owner_user_id} in one query), not Mongo itself.
"""

import copy

import pytest
import pytest_asyncio

import routers.projects as projects_router
from models.schemas import ApplyProjectFixRequest, ChatRequest, DownloadProjectRequest, FindingReasonRequest

USER_A = {"_id": "user-a-id", "email": "a@example.com"}
USER_B = {"_id": "user-b-id", "email": "b@example.com"}


class FakeProjectStore:
    def __init__(self):
        self.projects: dict[str, dict] = {}
        self._counter = 0

    async def save_project(self, project: dict, session_id: str, owner_user_id: str) -> str:
        self._counter += 1
        project_id = f"fake-project-{self._counter}"
        doc = {**copy.deepcopy(project), "_id": project_id, "session_id": session_id, "owner_user_id": owner_user_id}
        self.projects[project_id] = doc
        return project_id

    async def get_owned_project(self, project_id: str, owner_user_id: str):
        doc = self.projects.get(project_id)
        if doc is None or doc.get("owner_user_id") != owner_user_id:
            return None
        return copy.deepcopy(doc)

    async def get_owned_project_metadata(self, project_id: str, owner_user_id: str):
        return await self.get_owned_project(project_id, owner_user_id)

    async def update_owned_project(self, project_id: str, owner_user_id: str, updates: dict, **_kwargs):
        doc = self.projects.get(project_id)
        if doc is None or doc.get("owner_user_id") != owner_user_id:
            return
        doc.update(updates)


@pytest.fixture
def store(monkeypatch):
    fake = FakeProjectStore()
    monkeypatch.setattr(projects_router, "save_project", fake.save_project)
    monkeypatch.setattr(projects_router, "get_owned_project", fake.get_owned_project)
    monkeypatch.setattr(projects_router, "get_owned_project_metadata", fake.get_owned_project_metadata)
    monkeypatch.setattr(projects_router, "update_owned_project", fake.update_owned_project)
    return fake


def _sample_project() -> dict:
    return {
        "project": {"name": "acme-app", "languages": ["python"], "frameworks": [], "projectType": "python"},
        "files": [{"path": "app.py", "language": "python", "size": 20, "content": "print('secret')\n", "large_file": False}],
        "directories": [],
        "dependencies": [],
        "imports": [], "functions": [], "classes": [], "apiEndpoints": [],
        "tests": [], "configs": [], "deploymentFiles": [],
        "findings": [
            {
                "file": "app.py", "line": 1, "rule": "demo_rule", "category": "security",
                "severity": "medium", "message": "demo finding", "evidence": "print('secret')",
                "transform": {"original_snippet": "print('secret')\n", "proposed_fix": "logger.info('secret')\n"},
            }
        ],
        "warnings": [],
    }


@pytest_asyncio.fixture
async def project_a_id(store):
    return await store.save_project(_sample_project(), session_id="sess-a", owner_user_id=USER_A["_id"])


# ---------------------------------------------------------------- ownership assignment on creation

@pytest.mark.asyncio
async def test_upload_assigns_owner_from_auth_not_from_body(store, monkeypatch):
    """Ownership must come from the authenticated user, never from a
    client-suppliable field -- upload only takes session_id from the form,
    and that must NOT become (or influence) the owner."""
    import io

    from fastapi import UploadFile

    zip_bytes = _make_minimal_zip()
    upload = UploadFile(filename="proj.zip", file=io.BytesIO(zip_bytes))

    result = await projects_router.upload_project(file=upload, session_id="attacker-controlled", current_user=USER_A)
    saved = store.projects[result["project_id"]]
    assert saved["owner_user_id"] == USER_A["_id"]


def _make_minimal_zip() -> bytes:
    import zipfile
    from io import BytesIO

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("main.py", "print('hi')\n")
    return buf.getvalue()


# ---------------------------------------------------------------- CRITICAL: cross-user access blocked

@pytest.mark.asyncio
async def test_owner_can_read_own_project(store, project_a_id):
    result = await projects_router.get_project_by_id(project_a_id, current_user=USER_A)
    assert result["_id"] == project_a_id


@pytest.mark.asyncio
async def test_other_user_cannot_read_project(store, project_a_id):
    response = await projects_router.get_project_by_id(project_a_id, current_user=USER_B)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_other_user_cannot_score_project(store, project_a_id):
    response = await projects_router.score_project_by_id(project_a_id, current_user=USER_B)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_owner_can_score_own_project(store, project_a_id):
    result = await projects_router.score_project_by_id(project_a_id, current_user=USER_A)
    assert "overall_score" in result


@pytest.mark.asyncio
async def test_other_user_cannot_analyze_project(store, project_a_id):
    response = await projects_router.analyze_project_by_id(project_a_id, current_user=USER_B)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_other_user_cannot_reason_about_finding(store, project_a_id):
    response = await projects_router.reason_about_finding(
        project_a_id, FindingReasonRequest(finding_index=0), current_user=USER_B
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_other_user_cannot_generate_fix(store, project_a_id):
    response = await projects_router.transform_finding(
        project_a_id, FindingReasonRequest(finding_index=0), current_user=USER_B
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_other_user_cannot_apply_fix(store, project_a_id):
    response = await projects_router.apply_project_fix(
        project_a_id, ApplyProjectFixRequest(finding_index=0), current_user=USER_B
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_owner_can_apply_own_fix(store, project_a_id):
    result = await projects_router.apply_project_fix(
        project_a_id, ApplyProjectFixRequest(finding_index=0), current_user=USER_A
    )
    assert result["status"] == "applied"


@pytest.mark.asyncio
async def test_other_user_cannot_reanalyze_project(store, project_a_id):
    response = await projects_router.reanalyze_project(
        project_a_id, FindingReasonRequest(finding_index=0), current_user=USER_B
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_other_user_cannot_download_fixed_zip(store, project_a_id):
    response = await projects_router.download_fixed_project(project_a_id, current_user=USER_B)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_owner_can_download_own_fixed_zip(store, project_a_id):
    response = await projects_router.download_fixed_project(project_a_id, current_user=USER_A)
    assert response.status_code == 200
    assert response.media_type == "application/zip"


@pytest.mark.asyncio
async def test_other_user_cannot_chat_about_project(store, project_a_id):
    response = await projects_router.chat_about_project(
        project_a_id, ChatRequest(question="what does this app do"), current_user=USER_B
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_guessed_nonexistent_project_id_returns_404_for_anyone(store):
    response = await projects_router.get_project_by_id("fake-project-does-not-exist", current_user=USER_A)
    assert response.status_code == 404
    response = await projects_router.get_project_by_id("fake-project-does-not-exist", current_user=USER_B)
    assert response.status_code == 404
