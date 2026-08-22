import io
import zipfile

import pytest
from fastapi import UploadFile

from routers import projects
from services.auth import get_request_user


def _zip_bytes(entries: list[tuple[str, bytes | str]]) -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        for path, content in entries:
            zf.writestr(path, content)
    return archive.getvalue()


def test_zip_normalizes_dot_prefixed_paths_for_stable_file_lookup():
    project, _warnings, error = projects._project_from_zip_bytes(
        _zip_bytes([("./src/app.py", "print('ok')\n")]), "demo"
    )

    assert error is None
    assert project["files"][0]["path"] == "src/app.py"
    assert project["directories"] == ["src"]


def test_zip_rejects_duplicate_canonical_paths():
    project, _warnings, error = projects._project_from_zip_bytes(
        _zip_bytes([("app.py", "first\n"), ("./app.py", "second\n")]), "demo"
    )

    assert project is None
    assert error == {"error": "ZIP contains duplicate file paths"}


@pytest.mark.asyncio
async def test_demo_mode_zip_upload_uses_server_owned_demo_identity(monkeypatch):
    saved = {}

    async def save(project, session_id, owner_user_id):
        saved.update(project=project, session_id=session_id, owner_user_id=owner_user_id)
        return "project-1"

    monkeypatch.setattr(projects, "save_project", save)
    upload = UploadFile(
        filename="demo.zip",
        file=io.BytesIO(_zip_bytes([("app.py", "print('demo')\n"), ("assets/logo.bin", b"\x00\x01")])),
    )

    result = await projects.upload_project(
        upload,
        "browser-session-is-not-an-owner",
        current_user=await get_request_user(session_token=None),
    )

    assert result["project_id"] == "project-1"
    assert saved["owner_user_id"] == "demo-user"
    assert saved["session_id"] == "browser-session-is-not-an-owner"
    assert {entry["path"] for entry in saved["project"]["files"]} == {"app.py", "assets/logo.bin"}
