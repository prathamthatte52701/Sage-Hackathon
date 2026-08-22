"""Phase 3.9 certification: SEC-TLS-CORS-MISCONFIG."""

from services.analyzers.rules import run_rules
from services.security_rules import to_closed_world_findings


def _tls_cors_findings(code: str, language: str = "python") -> list[dict]:
    findings = to_closed_world_findings(run_rules("repository/app.py", language, code))
    return [finding for finding in findings if finding["rule_id"] == "SEC-TLS-CORS-MISCONFIG"]


def test_requests_verify_false_is_reported():
    findings = _tls_cors_findings("requests.get('https://api.example.com', verify=False)")

    assert len(findings) == 1
    assert findings[0]["cwe"] == "CWE-295"


def test_httpx_verify_false_is_reported():
    assert len(_tls_cors_findings("httpx.get('https://api.example.com', verify=False)")) == 1


def test_unrelated_verify_variable_and_verify_true_are_silent():
    assert _tls_cors_findings("verify = False\nrequests.get('https://api.example.com', verify=True)") == []


def test_credentialed_python_wildcard_cors_is_reported():
    code = "app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True)"

    assert len(_tls_cors_findings(code)) == 1


def test_restricted_and_explicit_public_python_cors_are_silent():
    restricted = "app.add_middleware(CORSMiddleware, allow_origins=['https://app.example.com'], allow_credentials=True)"
    public = "app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False)"

    assert _tls_cors_findings(restricted) == []
    assert _tls_cors_findings(public) == []


def test_credentialed_javascript_wildcard_cors_is_reported():
    assert len(_tls_cors_findings("app.use(cors({ origin: '*', credentials: true }))", "javascript")) == 1


def test_public_javascript_cors_and_comments_are_silent():
    code = "app.use(cors({ origin: '*', credentials: false }));\n// process.env.NODE_TLS_REJECT_UNAUTHORIZED = 0"

    assert _tls_cors_findings(code, "javascript") == []
