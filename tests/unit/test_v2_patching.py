import io
import zipfile

import pytest
from fastapi.responses import JSONResponse, Response

from models.schemas import ApplyProjectFixRequest
from routers import projects
from services.patching import (
    PatchError,
    apply_exact_replacement,
    apply_many_exact_replacements,
    build_patch_metadata,
    safe_archive_path,
    source_hash,
)


def test_exact_patch_applies_and_preserves_unaffected_code():
    content = "const a = 1;\nconst amount = Number(value) || 0;\nconst z = 3;\n"
    applied = apply_exact_replacement(content, "const amount = Number(value) || 0;", "const amount = Number(value);")

    assert "const a = 1;" in applied.patched
    assert "const z = 3;" in applied.patched
    assert "Number(value) || 0" not in applied.patched


def test_invalid_and_conflicting_patch_rejected():
    with pytest.raises(PatchError):
        apply_exact_replacement("abc", "missing", "x")
    with pytest.raises(PatchError):
        apply_many_exact_replacements("abc abc", [("abc", "x")])


def test_exact_single_match_patch_validates_and_applies():
    content = "const a = 1;\nlet pendingUser = user;\nreturn pendingUser;\n"
    fixed = "let pendingUser = user;\ntry {\n  return pendingUser;\n} finally {\n  pendingUser = null;\n}"
    metadata = build_patch_metadata(content, "let pendingUser = user;\nreturn pendingUser;", fixed)
    applied = apply_exact_replacement(content, "let pendingUser = user;\nreturn pendingUser;", fixed)

    assert metadata["can_apply"] is True
    assert metadata["apply_failure_reason"] == ""
    assert metadata["source_hash"] == source_hash(content)
    assert "const a = 1;" in applied.patched
    assert "finally" in applied.patched


def test_stale_source_patch_rejected():
    metadata = build_patch_metadata(
        "const value = 2;\n",
        "const value = 2;",
        "const value = 3;",
        expected_hash=source_hash("const value = 1;\n"),
    )

    assert metadata["can_apply"] is False
    assert metadata["apply_failure_reason"] == "stale_source"


def test_missing_target_patch_rejected():
    metadata = build_patch_metadata("const value = 2;\n", "const missing = 1;", "const missing = 2;")

    assert metadata["can_apply"] is False
    assert metadata["apply_failure_reason"] == "target_not_found"


def test_duplicated_ambiguous_target_patch_rejected():
    metadata = build_patch_metadata("let x = 1;\nlet x = 1;\n", "let x = 1;", "let x = 2;")

    assert metadata["can_apply"] is False
    assert metadata["apply_failure_reason"] == "ambiguous_target"


def test_overlapping_patch_rejected():
    metadata = build_patch_metadata(
        "abcdef",
        "bcd",
        "BCD",
        existing_spans=[(2, 5)],
    )

    assert metadata["can_apply"] is False
    assert metadata["apply_failure_reason"] == "overlapping_patch"


def test_malformed_fix_rejected():
    metadata = build_patch_metadata("abcdef", "", "ABC")

    assert metadata["can_apply"] is False
    assert metadata["apply_failure_reason"] == "malformed_fix"


def test_zip_path_security():
    assert safe_archive_path("src/app.js") == "src/app.js"
    with pytest.raises(PatchError):
        safe_archive_path("../secret.txt")
    with pytest.raises(PatchError):
        safe_archive_path("/absolute.txt")


@pytest.mark.asyncio
async def test_project_apply_fix_patches_only_target_file(monkeypatch):
    project = {
        "_id": "p1",
        "session_id": "s1",
        "project": {"name": "demo"},
        "files": [
            {"path": "src/a.js", "language": "javascript", "content": "const amount = Number(value) || 0;\n"},
            {"path": "src/b.js", "language": "javascript", "content": "const untouched = true;\n"},
        ],
        "findings": [
            {
                "file": "src/a.js",
                "line": 1,
                "rule": "js_numeric_coercion_default",
                "transform": {
                    "original_snippet": "const amount = Number(value) || 0;",
                    "proposed_fix": "const amount = Number(value);",
                },
            }
        ],
        "imports": [],
        "functions": [],
        "classes": [],
        "apiEndpoints": [],
        "tests": [],
        "configs": [],
        "deploymentFiles": [],
        "warnings": [],
    }
    saved = {}

    async def fake_get_owned_project(_id, _owner_user_id):
        return project

    async def fake_update_owned_project(_id, _owner_user_id, updates, **_kwargs):
        saved.update(updates)

    monkeypatch.setattr(projects, "get_owned_project", fake_get_owned_project)
    monkeypatch.setattr(projects, "update_owned_project", fake_update_owned_project)

    result = await projects.apply_project_fix(
        "p1", ApplyProjectFixRequest(finding_index=0), current_user={"_id": "test-user"}
    )

    assert result["status"] == "applied"
    patched_a = next(f for f in saved["files"] if f["path"] == "src/a.js")
    untouched_b = next(f for f in saved["files"] if f["path"] == "src/b.js")
    assert "Number(value) || 0" not in patched_a["content"]
    assert untouched_b["content"] == "const untouched = true;\n"


@pytest.mark.asyncio
async def test_download_fixed_zip_preserves_paths_and_content(monkeypatch):
    project = {
        "project": {"name": "demo"},
        "files": [
            {"path": "src/app.js", "content": "patched"},
            {"path": "README.md", "content": "readme"},
            {"path": ".env", "content": "SECRET=1"},
        ],
    }

    async def fake_get_owned_project(_id, _owner_user_id):
        return project

    monkeypatch.setattr(projects, "get_owned_project", fake_get_owned_project)
    response = await projects.download_fixed_project("p1", current_user={"_id": "test-user"})

    assert isinstance(response, Response)
    body = b"".join([chunk async for chunk in response.body_iterator])
    zf = zipfile.ZipFile(io.BytesIO(body))
    assert set(zf.namelist()) == {"src/app.js", "README.md"}
    assert zf.read("src/app.js").decode() == "patched"


@pytest.mark.asyncio
async def test_download_fixed_zip_rejects_traversal(monkeypatch):
    async def fake_get_owned_project(_id, _owner_user_id):
        return {"project": {"name": "demo"}, "files": [{"path": "../evil.js", "content": "x"}]}

    monkeypatch.setattr(projects, "get_owned_project", fake_get_owned_project)
    response = await projects.download_fixed_project("p1", current_user={"_id": "test-user"})

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
