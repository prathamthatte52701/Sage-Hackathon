import io
import zipfile

import pytest

from routers.projects import MAX_FILE_COUNT, MAX_SINGLE_FILE_UNCOMPRESSED, _project_from_zip_bytes, _read_upload_capped


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def test_zip_path_traversal_rejected():
    project, warnings, error = _project_from_zip_bytes(_zip_bytes({"../../evil.py": "print(1)"}), "bad")
    assert project is None
    assert warnings is None
    assert error["error"] == "ZIP contains unsafe file paths"


def test_zip_upload_builds_normalized_project():
    project, warnings, error = _project_from_zip_bytes(_zip_bytes({"app.py": "print('ok')"}), "ok")
    assert error is None
    assert warnings == []
    assert project["files"][0]["path"] == "app.py"
    assert project["project"]["languages"] == ["python"]


def test_zip_rejects_excessive_path_depth():
    deep_path = "/".join([f"d{i}" for i in range(25)]) + "/app.py"
    project, warnings, error = _project_from_zip_bytes(_zip_bytes({deep_path: "print(1)"}), "deep")
    assert project is None
    assert warnings is None
    assert error["error"] == "ZIP contains unsafe file paths"


def test_zip_extracts_manifest_dependencies():
    project, warnings, error = _project_from_zip_bytes(
        _zip_bytes({"requirements.txt": "fastapi==1.0\n# comment\nhttpx>=0.1\n"}),
        "deps",
    )
    assert error is None
    assert {"name": "fastapi", "version": "==1.0", "source": "requirements.txt"} in project["dependencies"]
    assert {"name": "httpx", "version": ">=0.1", "source": "requirements.txt"} in project["dependencies"]


def test_zip_bomb_per_file_decompressed_size_capped():
    """A single source file that decompresses past MAX_SINGLE_FILE_UNCOMPRESSED
    must be rejected even though its compressed size on disk is tiny and the
    aggregate archive is nowhere near the 600MB total cap -- this is the
    protection the old code never had (it only summed header-declared sizes
    before reading, never bounded actual bytes read per file)."""
    huge_source = "x = 1  # padding\n" * ((MAX_SINGLE_FILE_UNCOMPRESSED // 17) + 1000)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.py", huge_source)
    project, warnings, error = _project_from_zip_bytes(buffer.getvalue(), "bomb")
    assert project is None
    assert "too large after decompression" in error["error"]


def test_zip_excessive_file_count_rejected():
    entries = {f"file_{i}.py": "x = 1\n" for i in range(MAX_FILE_COUNT + 1)}
    project, warnings, error = _project_from_zip_bytes(_zip_bytes(entries), "many")
    assert project is None
    assert "too many files" in error["error"]


def test_malformed_zip_bytes_returns_clean_error_not_crash():
    project, warnings, error = _project_from_zip_bytes(b"this is not a zip file at all", "bad")
    assert project is None
    assert error["error"] == "Uploaded file is not a valid ZIP archive"


class _FakeUploadFile:
    """Minimal stand-in for FastAPI's UploadFile.read(size) -- avoids pulling
    in a full UploadFile/SpooledTemporaryFile for a pure chunking test."""

    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    async def read(self, size: int) -> bytes:
        return self._buf.read(size)


@pytest.mark.asyncio
async def test_upload_capped_read_rejects_oversized_body_without_buffering_it_all():
    oversized = _FakeUploadFile(b"a" * 1000)
    result = await _read_upload_capped(oversized, max_size=500)
    assert result is None


@pytest.mark.asyncio
async def test_upload_capped_read_accepts_body_within_limit():
    data = b"a" * 1000
    within_limit = _FakeUploadFile(data)
    result = await _read_upload_capped(within_limit, max_size=2000)
    assert result == data
