"""Phase 3.6 certification: SEC-PATH-TRAVERSAL-FILE."""

from services.analyzers.rules import run_rules
from services.security_rules import to_closed_world_findings


def _path_findings(code: str) -> list[dict]:
    findings = to_closed_world_findings(run_rules("repository/app.py", "python", code))
    return [finding for finding in findings if finding["rule_id"] == "SEC-PATH-TRAVERSAL-FILE"]


def test_direct_request_path_to_open_is_reported():
    findings = _path_findings("open(request.args['path']).read()")

    assert len(findings) == 1
    assert findings[0]["cwe"] == "CWE-22"
    assert findings[0]["deterministic_evidence"] is True


def test_propagated_request_path_to_pathlib_read_is_reported():
    code = "target = request.get_json()['path']\nPath(target).read_text()"

    assert len(_path_findings(code)) == 1


def test_static_root_joined_with_filename_parameter_is_reported():
    code = "UPLOAD_ROOT = Path('/srv/app/uploads')\ndef read_upload(filename):\n    return (UPLOAD_ROOT / filename).read_text()"

    assert len(_path_findings(code)) == 1


def test_direct_request_path_to_remove_is_reported():
    assert len(_path_findings("os.remove(req.query['path'])")) == 1


def test_static_file_path_is_not_reported():
    assert _path_findings("open('/srv/app/config.json').read()") == []


def test_generic_helper_path_is_not_assumed_to_be_user_controlled():
    assert _path_findings("def load(path):\n    return open(path).read()") == []


def test_root_containment_guard_is_respected():
    code = """
UPLOAD_ROOT = Path('/srv/app/uploads')
def read_upload(filename):
    target = (UPLOAD_ROOT / filename).resolve()
    if UPLOAD_ROOT not in target.parents:
        raise ValueError('outside root')
    return target.read_text()
"""

    assert _path_findings(code) == []


def test_comment_and_string_are_not_reported():
    code = "# open(request.args['path'])\nexample = \"Path(request.args['path']).read_text()\""

    assert _path_findings(code) == []


def test_repeated_analysis_is_deterministic():
    code = "open(request.args['path']).read()"
    runs = [_path_findings(code) for _ in range(10)]

    assert all(run == runs[0] for run in runs)
    assert runs[0][0]["line"] == 1
