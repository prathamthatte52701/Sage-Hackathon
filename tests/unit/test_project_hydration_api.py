import pytest
from fastapi.responses import JSONResponse

from routers import projects


USER_A = {"_id": "user-a"}
USER_B = {"_id": "user-b"}


@pytest.mark.asyncio
async def test_metadata_endpoint_does_not_depend_on_full_project_hydration(monkeypatch):
    async def metadata(project_id, owner_user_id):
        assert owner_user_id == USER_A["_id"]
        return {"_id": project_id, "files": [{"path": "app.py", "content_ref": "grid-id"}]}

    monkeypatch.setattr(projects, "get_owned_project_metadata", metadata)
    result = await projects.get_project_metadata("project-1", current_user=USER_A)

    assert result["files"][0].get("content") is None
    assert result["files"][0]["content_ref"] == "grid-id"


@pytest.mark.asyncio
async def test_file_endpoint_is_owner_scoped(monkeypatch):
    async def owned_file(project_id, owner_user_id, path):
        if owner_user_id != USER_A["_id"]:
            return None
        return {"path": path, "content": "print('safe')\n"}

    monkeypatch.setattr(projects, "get_owned_project_file", owned_file)
    allowed = await projects.get_project_file("project-1", "app.py", current_user=USER_A)
    denied = await projects.get_project_file("project-1", "app.py", current_user=USER_B)

    assert allowed["content"] == "print('safe')\n"
    assert isinstance(denied, JSONResponse)
    assert denied.status_code == 404
