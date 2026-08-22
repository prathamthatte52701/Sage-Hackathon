"""Phase 3.5 certification: SEC-SSRF.

Supported evidence is a local attacker-controlled URL reaching an explicit
HTTP client sink. Fixed server hosts and static allowlist guards are accepted;
function names such as ``sanitize_url`` are not treated as proof of safety.
"""

from services.analyzers.rules import run_rules
from services.security_rules import to_closed_world_findings


def _ssrf_findings(code: str, language: str = "python") -> list[dict]:
    findings = to_closed_world_findings(run_rules("repository/app.py", language, code))
    return [finding for finding in findings if finding["rule_id"] == "SEC-SSRF"]


def test_python_direct_request_url_to_requests_is_reported():
    findings = _ssrf_findings("requests.get(request.args['url'])")

    assert len(findings) == 1
    assert findings[0]["cwe"] == "CWE-918"
    assert findings[0]["deterministic_evidence"] is True


def test_python_request_url_propagates_to_httpx():
    code = "url = request.get_json()['url']\nhttpx.post(url)"

    assert len(_ssrf_findings(code)) == 1


def test_python_urllib_and_import_aliases_are_reported():
    urllib_code = "from urllib.request import urlopen as fetch_url\nfetch_url(req.query['url'])"
    httpx_code = "import requests as http\nhttp.get(request.form['url'])"

    assert len(_ssrf_findings(urllib_code)) == 1
    assert len(_ssrf_findings(httpx_code)) == 1


def test_python_route_url_parameter_reaching_http_sink_is_reported():
    code = "@app.get('/preview')\ndef preview(url: str):\n    return requests.get(url, timeout=4)"

    assert len(_ssrf_findings(code)) == 1


def test_python_request_method_uses_second_positional_url_argument():
    assert len(_ssrf_findings("requests.request('GET', request.args['url'])")) == 1


def test_python_fake_sanitizer_name_does_not_suppress_flow():
    code = "url = sanitize_url(request.args['url'])\nrequests.get(url)"

    assert len(_ssrf_findings(code)) == 1


def test_python_static_url_is_not_reported():
    assert _ssrf_findings("requests.get('https://api.example.com/health')") == []


def test_python_fixed_server_host_with_untrusted_path_is_not_reported():
    code = "url = f\"https://api.example.com/users/{request.args['user_id']}\"\nrequests.get(url)"

    assert _ssrf_findings(code) == []


def test_python_static_allowlist_guard_is_respected():
    code = """
ALLOWED_URLS = {'https://api.example.com/health'}
@app.get('/preview')
def preview(url):
    if url not in ALLOWED_URLS:
        return None
    return requests.get(url)
"""

    assert _ssrf_findings(code) == []


def test_python_comment_and_string_are_not_reported():
    code = "# requests.get(request.args['url'])\nexample = \"httpx.get(request.args['url'])\""

    assert _ssrf_findings(code) == []


def test_javascript_direct_request_url_to_fetch_is_reported():
    findings = _ssrf_findings("fetch(req.query.url)", "javascript")

    assert len(findings) == 1
    assert findings[0]["cwe"] == "CWE-918"


def test_javascript_url_propagates_to_axios():
    code = "const target = req.body.url;\naxios.get(target);"

    assert len(_ssrf_findings(code, "javascript")) == 1


def test_javascript_got_and_request_body_url_are_reported():
    assert len(_ssrf_findings("got.post(request.body.url)", "typescript")) == 1


def test_javascript_static_url_and_fixed_host_path_are_not_reported():
    code = "fetch('https://api.example.com/health');\nfetch(`https://api.example.com/users/${req.params.id}`);"

    assert _ssrf_findings(code, "javascript") == []


def test_javascript_comment_and_string_are_not_reported():
    code = "// fetch(req.query.url)\nconst example = \"axios.get(req.query.url)\";"

    assert _ssrf_findings(code, "javascript") == []


def test_repeated_ssrf_analysis_is_deterministic():
    code = "requests.get(request.args['url'])"
    runs = [_ssrf_findings(code) for _ in range(10)]

    assert all(run == runs[0] for run in runs)
    assert runs[0][0]["line"] == 1
