import io
import zipfile

from routers.projects import _project_from_zip_bytes


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
