"""Phase 3.8 certification: SEC-EVAL-EXEC."""

from services.analyzers.rules import run_rules
from services.security_rules import to_closed_world_findings


def _eval_findings(code: str, language: str = "python") -> list[dict]:
    findings = to_closed_world_findings(run_rules("repository/app.py", language, code))
    return [finding for finding in findings if finding["rule_id"] == "SEC-EVAL-EXEC"]


def test_python_eval_request_input_is_reported():
    findings = _eval_findings("eval(request.args['expression'])")

    assert len(findings) == 1
    assert findings[0]["cwe"] == "CWE-95"
    assert findings[0]["deterministic_evidence"] is True


def test_python_exec_and_local_expression_are_reported():
    code = "expression = request.json['code']\nexec(expression)"

    assert len(_eval_findings(code)) == 1


def test_python_comments_and_strings_are_not_reported():
    code = "# eval(request.args['expression'])\nexample = \"exec(payload)\""

    assert _eval_findings(code) == []


def test_javascript_eval_request_input_is_reported():
    findings = _eval_findings("eval(req.body.expression)", "javascript")

    assert len(findings) == 1
    assert findings[0]["cwe"] == "CWE-95"


def test_javascript_eval_comments_and_strings_are_not_reported():
    code = "// eval(req.body.expression)\nconst example = \"eval(payload)\";"

    assert _eval_findings(code, "typescript") == []


def test_repeated_analysis_is_deterministic():
    runs = [_eval_findings("eval(payload)") for _ in range(10)]

    assert all(run == runs[0] for run in runs)
    assert runs[0][0]["line"] == 1
