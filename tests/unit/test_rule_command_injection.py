"""Phase 3.4 certification: SEC-COMMAND-INJECTION.

The supported surface is a local request/input flow into the recognized Python
or Node command APIs. Static argv/constant commands stay silent; cross-file
taint is intentionally deferred to Phase 4.
"""

from services.analyzers.rules import run_rules
from services.security_rules import to_closed_world_findings


def _command_findings(code: str, language: str = "python") -> list[dict]:
    findings = to_closed_world_findings(run_rules("repository/app.py", language, code))
    return [finding for finding in findings if finding["rule_id"] == "SEC-COMMAND-INJECTION"]


def test_python_shell_true_with_direct_request_command_is_reported():
    findings = _command_findings("subprocess.run(request.args['cmd'], shell=True)")

    assert len(findings) == 1
    assert findings[0]["cwe"] == "CWE-78"
    assert findings[0]["deterministic_evidence"] is True


def test_python_string_construction_from_request_is_reported():
    findings = _command_findings("subprocess.run(f\"grep {request.args['term']} logs.txt\", shell=True)")

    assert len(findings) == 1


def test_python_os_system_with_request_input_is_reported():
    findings = _command_findings("os.system(request.json['cmd'])")

    assert len(findings) == 1


def test_python_alias_import_and_local_propagation_are_reported():
    code = "from subprocess import run as run_command\ncmd = request.form['cmd']\nrun_command(cmd, shell=True)"

    assert len(_command_findings(code)) == 1


def test_python_attacker_controlled_argv_argument_is_reported_without_shell():
    findings = _command_findings("subprocess.run(['git', 'show', request.args['revision']])")

    assert len(findings) == 1


def test_python_static_argv_is_not_reported():
    assert _command_findings("subprocess.run(['git', 'status'])") == []


def test_python_constant_command_without_shell_is_not_reported():
    assert _command_findings("subprocess.run('git status')") == []


def test_python_comment_and_string_are_not_reported():
    code = "# os.system(request.args['cmd'])\nexample = \"subprocess.run(request.args['cmd'], shell=True)\""

    assert _command_findings(code) == []


def test_javascript_exec_with_direct_request_command_is_reported():
    findings = _command_findings("child_process.exec(req.query.cmd)", "javascript")

    assert len(findings) == 1
    assert findings[0]["cwe"] == "CWE-78"


def test_javascript_template_command_with_request_input_is_reported():
    findings = _command_findings("child_process.exec(`grep ${req.body.term} logs.txt`)", "javascript")

    assert len(findings) == 1


def test_javascript_spawn_with_attacker_controlled_argument_is_reported():
    findings = _command_findings("child_process.spawn('git', ['show', req.params.revision], { shell: false })", "javascript")

    assert len(findings) == 1


def test_javascript_require_alias_and_local_propagation_are_reported():
    code = "const { exec: execute } = require('child_process');\nconst command = req.body.command;\nexecute(command);"

    assert len(_command_findings(code, "javascript")) == 1


def test_javascript_namespace_alias_is_reported():
    code = "import * as cp from 'child_process';\ncp.exec(req.query.command);"

    assert len(_command_findings(code, "typescript")) == 1


def test_javascript_static_argv_without_shell_is_not_reported():
    code = "child_process.spawn('git', ['status'], { shell: false });"

    assert _command_findings(code, "javascript") == []


def test_javascript_comment_and_string_are_not_reported():
    code = "// child_process.exec(req.query.cmd)\nconst example = \"child_process.exec(req.query.cmd)\";"

    assert _command_findings(code, "javascript") == []


def test_repeated_analysis_is_deterministic_and_keeps_direct_finding_location():
    code = "subprocess.run(request.args['cmd'], shell=True)"
    runs = [_command_findings(code) for _ in range(10)]

    assert all(run == runs[0] for run in runs)
    assert runs[0][0]["line"] == 1
