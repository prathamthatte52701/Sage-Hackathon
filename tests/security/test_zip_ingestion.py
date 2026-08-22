import io
import tempfile
import time
import zipfile

import pytest

from routers.projects import MAX_REPOSITORY_FILES, MAX_SINGLE_FILE_UNCOMPRESSED, UPLOAD_SPOOL_THRESHOLD, _project_from_zip_bytes, _read_upload_capped


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


def test_binary_asset_is_preserved_for_storage_round_trip():
    payload = b"\x89PNG\r\n\x1a\n\x00\x01asset"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("src/app.py", "print('ok')\n")
        zf.writestr("assets/logo.png", payload)

    project, _warnings, error = _project_from_zip_bytes(archive.getvalue(), "demo")

    assert error is None
    asset = next(file for file in project["files"] if file["path"] == "assets/logo.png")
    assert asset["content"] is None
    assert asset["binary_content"] == payload


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
    entries = {f"file_{i}.py": "x = 1\n" for i in range(MAX_REPOSITORY_FILES + 1)}
    project, warnings, error = _project_from_zip_bytes(_zip_bytes(entries), "many")
    assert project is None
    assert "analyzable files" in error["error"]
    assert f"{MAX_REPOSITORY_FILES:,}" in error["error"]


def test_zip_at_exactly_the_file_limit_is_accepted():
    entries = {f"file_{i}.py": "x = 1\n" for i in range(MAX_REPOSITORY_FILES)}
    project, warnings, error = _project_from_zip_bytes(_zip_bytes(entries), "exact")
    assert error is None
    assert len(project["files"]) == MAX_REPOSITORY_FILES


def test_zip_one_over_the_file_limit_is_rejected_cleanly():
    entries = {f"file_{i}.py": "x = 1\n" for i in range(MAX_REPOSITORY_FILES + 1)}
    project, warnings, error = _project_from_zip_bytes(_zip_bytes(entries), "over")
    assert project is None
    assert warnings is None
    assert "Repository contains" in error["error"]


def test_2500_eligible_files_is_accepted():
    entries = {f"src/file_{i}.py": "x = 1\n" for i in range(2500)}
    project, _warnings, error = _project_from_zip_bytes(_zip_bytes(entries), "mid")
    assert error is None
    assert len(project["files"]) == 2500


def test_4999_eligible_files_is_accepted():
    entries = {f"src/file_{i}.py": "x = 1\n" for i in range(4999)}
    project, _warnings, error = _project_from_zip_bytes(_zip_bytes(entries), "almost")
    assert error is None
    assert len(project["files"]) == 4999


def test_dependency_junk_does_not_count_toward_the_eligible_file_limit():
    """A ZIP whose raw entry count (10,300) is well past MAX_REPOSITORY_FILES
    must still be accepted when almost all of that is node_modules noise --
    only the real source files count toward the cap."""
    entries = {f"node_modules/pkg{i}/index.js": "module.exports = {};\n" for i in range(10_000)}
    entries.update({f"src/feature_{i}.py": "x = 1\n" for i in range(300)})
    project, warnings, error = _project_from_zip_bytes(_zip_bytes(entries), "noisy")
    assert error is None
    assert len(project["files"]) == 300
    assert all(f["path"].startswith("src/") for f in project["files"])
    assert any("node_modules" in w for w in warnings)


def test_binary_assets_do_not_count_toward_the_eligible_file_limit():
    """3000 real source files plus 5000 images -- the images are still
    stored (round-trip fidelity) but must not push this over the cap."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for i in range(3000):
            zf.writestr(f"src/module_{i}.py", "x = 1\n")
        for i in range(5000):
            zf.writestr(f"assets/img_{i}.png", b"\x89PNG\r\n\x1a\n\x00fake")

    project, _warnings, error = _project_from_zip_bytes(buffer.getvalue(), "assets")
    assert error is None
    assert len(project["files"]) == 8000  # all of them are still stored...
    png_files = [f for f in project["files"] if f["path"].endswith(".png")]
    assert len(png_files) == 5000
    assert all(f["content"] is None and f["binary_content"] for f in png_files)  # ...but as binary, not source


def test_many_junk_extension_files_stay_cheap_and_untranscoded():
    """Bug 2: 2000 files of an extension nobody analyzes, alongside 50 real
    .py files and a few recognized config/manifest files. Upload cost must
    track the handful of real files, not the pile of junk, and only the
    recognized Python/config/deployment set gets UTF-8-decoded as source --
    everything else is still stored (round-trip fidelity) but left as raw
    bytes instead of wastefully decoded."""
    entries = {f"assets/blob_{i}.xyzjunk": "junk-content" for i in range(2000)}
    entries.update({f"src/module_{i}.py": "x = 1\n" for i in range(50)})
    entries["config/settings.yaml"] = "debug: true\n"
    entries["stubs/module.pyi"] = "def f() -> int: ...\n"
    entries["README.md"] = "# hello\n"

    start = time.perf_counter()
    project, warnings, error = _project_from_zip_bytes(_zip_bytes(entries), "junky")
    elapsed = time.perf_counter() - start

    assert error is None
    assert elapsed < 2.0, f"took {elapsed:.2f}s -- junk-extension files should be cheap to classify"
    assert len(project["files"]) == 2053

    by_path = {f["path"]: f for f in project["files"]}
    assert by_path["src/module_0.py"]["content"] == "x = 1\n"
    assert by_path["config/settings.yaml"]["content"] == "debug: true\n"
    assert by_path["stubs/module.pyi"]["content"] == "def f() -> int: ...\n"
    assert by_path["README.md"]["content"] == "# hello\n"

    junk_files = [f for f in project["files"] if f["path"].endswith(".xyzjunk")]
    assert len(junk_files) == 2000
    assert all(f["content"] is None and f["binary_content"] is not None for f in junk_files)


def test_completely_empty_zip_is_handled_cleanly():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w"):
        pass  # zero entries
    project, warnings, error = _project_from_zip_bytes(buffer.getvalue(), "empty")
    assert error is None
    assert project["files"] == []
    assert project["project"]["projectType"] == "unknown"


def test_zip_with_only_junk_directory_files_is_handled_cleanly():
    """Nothing eligible survives filtering, but that's a valid (if useless)
    upload, not a crash or a false rejection."""
    entries = {f"node_modules/pkg{i}/index.js": "x\n" for i in range(50)}
    entries["dist/bundle.js"] = "x\n"
    project, warnings, error = _project_from_zip_bytes(_zip_bytes(entries), "junk-only")
    assert error is None
    assert project["files"] == []
    assert any("node_modules" in w for w in warnings)
    assert any("dist" in w for w in warnings)


def test_zip_duplicate_file_paths_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("app.py", "a = 1\n")
        zf.writestr("app.py", "a = 2\n")
    project, warnings, error = _project_from_zip_bytes(buffer.getvalue(), "dup")
    assert project is None
    assert warnings is None
    assert error["error"] == "ZIP contains duplicate file paths"


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
    try:
        assert result.read() == data
    finally:
        result.close()


@pytest.mark.asyncio
async def test_upload_capped_read_streams_to_spooled_file_not_one_bytes_blob():
    """Bug 1 fix: the capped reader must hand back a seekable spooled file
    (RAM up to UPLOAD_SPOOL_THRESHOLD, then disk) instead of the old
    chunks-list-then-`b"".join` result, which -- despite reading in bounded
    chunks -- still ended up holding the whole body as one Python bytes
    object before _project_from_zip_bytes ever saw it."""
    data = b"z" * (UPLOAD_SPOOL_THRESHOLD + (1024 * 1024))  # forces disk rollover
    upload = _FakeUploadFile(data)
    result = await _read_upload_capped(upload, max_size=len(data) + 1)
    try:
        assert isinstance(result, tempfile.SpooledTemporaryFile)
        assert not isinstance(result, (bytes, bytearray))
        assert result.tell() == 0  # left seeked-to-start for the next reader
        assert result.read() == data  # disk-spilled content survives intact
    finally:
        result.close()
