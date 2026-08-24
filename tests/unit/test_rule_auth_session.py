"""Phase 3.11 certification: SEC-AUTH-SESSION."""

from services.analyzers.rules import run_rules
from services.security_rules import to_closed_world_findings


def _auth_findings(code: str) -> list[dict]:
    findings = to_closed_world_findings(run_rules("repository/app.py", "python", code))
    return [finding for finding in findings if finding["rule_id"] == "SEC-AUTH-SESSION"]


def test_jwt_signature_verification_bypass_is_reported():
    code = "import jwt\njwt.decode(token, options={'verify_signature': False})"

    findings = _auth_findings(code)

    assert len(findings) == 1
    assert findings[0]["rule"] == "jwt_signature_verification_disabled"
    assert findings[0]["cwe"] == "CWE-287"


def test_direct_decode_alias_and_none_algorithm_are_reported():
    code = "from jwt import decode as decode_token\ndecode_token(token, algorithms=['none'])"

    findings = _auth_findings(code)

    assert len(findings) == 1
    assert findings[0]["rule"] == "jwt_algorithm_verification_bypass"


def test_verified_jwt_decode_is_silent():
    code = "import jwt\njwt.decode(token, secret, algorithms=['HS256'])"

    assert _auth_findings(code) == []


def test_insecure_named_auth_cookie_is_reported():
    code = "response.set_cookie('session_token', token, httponly=False, secure=False)"

    findings = _auth_findings(code)

    assert len(findings) == 1
    assert findings[0]["rule"] == "insecure_auth_cookie"


def test_secure_auth_cookie_and_unrelated_cookie_are_silent():
    secure = "response.set_cookie('session_token', token, httponly=True, secure=True, samesite='lax')"
    unrelated = "response.set_cookie('theme', 'dark', httponly=False, secure=False)"

    assert _auth_findings(secure) == []
    assert _auth_findings(unrelated) == []


def test_javascript_insecure_auth_cookie_is_reported():
    code = "res.cookie('access_token', token, { httpOnly: false, secure: false });"
    findings = to_closed_world_findings(run_rules("repository/app.js", "javascript", code))

    assert [finding["rule"] for finding in findings] == ["insecure_auth_cookie"]


def test_javascript_secure_cookie_and_comment_are_silent():
    secure = "res.cookie('access_token', token, { httpOnly: true, secure: true, sameSite: 'lax' });"
    comment = "// res.cookie('access_token', token, { httpOnly: false, secure: false });"

    assert to_closed_world_findings(run_rules("repository/app.js", "javascript", secure)) == []
    assert to_closed_world_findings(run_rules("repository/app.js", "javascript", comment)) == []


def test_jwt_secret_literal_fallback_is_a_hardcoded_secret_finding():
    code = "import os\nJWT_SECRET = os.getenv('JWT_SECRET', 'dev-secret')"
    findings = to_closed_world_findings(run_rules("repository/app.py", "python", code))

    assert [finding["rule_id"] for finding in findings] == ["SEC-HARDCODED-SECRET"]
    assert findings[0]["rule"] == "jwt_insecure_secret_fallback"


def test_empty_auth_environment_fallbacks_are_not_hardcoded_secret_findings():
    getenv_code = "import os\nJWT_SECRET = os.getenv('JWT_SECRET', '')"
    environ_get_code = "import os\nAPP_TOKEN = os.environ.get('APP_TOKEN', '')"

    assert to_closed_world_findings(run_rules("repository/app.py", "python", getenv_code)) == []
    assert to_closed_world_findings(run_rules("repository/app.py", "python", environ_get_code)) == []


def test_placeholder_auth_environment_fallback_is_not_hardcoded_secret_finding():
    code = "import os\nAPP_TOKEN = os.getenv('APP_TOKEN', 'changeme')"

    assert to_closed_world_findings(run_rules("repository/app.py", "python", code)) == []


def test_non_auth_environment_default_and_comments_are_silent():
    code = "import os\nDATABASE_URL = os.getenv('DATABASE_URL', 'postgres://localhost/app')\n# jwt.decode(token, options={'verify_signature': False})"

    assert _auth_findings(code) == []


def test_repeated_analysis_is_deterministic():
    code = "import jwt\njwt.decode(token, options={'verify_signature': False})"
    runs = [_auth_findings(code) for _ in range(10)]

    assert all(run == runs[0] for run in runs)
