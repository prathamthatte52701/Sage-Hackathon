import ast

from services.analyzer import analyze_project
from services.analyzers.python_taint import analyze_python_taint


def rules(source: str):
    return analyze_python_taint("app.py", source)


def only_rule(source: str, rule: str):
    return [item for item in rules(source) if item["rule"] == rule]


def test_sql_direct_request_to_execute_has_source_sink_evidence():
    findings = only_rule('cursor.execute(request.args["id"])', "sql_injection")
    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"
    assert findings[0]["confidence"] == "high"
    assert findings[0]["evidence_type"] == "ast_source_sink"
    assert findings[0]["source_line"] == 1
    assert "cursor.execute" in findings[0]["sink_expression"]


def test_sql_variable_chain_and_alias_are_tainted():
    source = """
req = request
a = req.args["id"]
b = a
c = b
cursor.execute(c)
"""
    assert len(only_rule(source, "sql_injection")) == 1


def test_sql_concatenation_fstring_and_container_propagate():
    source = """
user_id = request.args.get("id")
query = "SELECT " + user_id
cursor.execute(query)
html_payload = {"value": user_id}
cursor.executemany("SELECT " + html_payload["value"])
"""
    assert len(only_rule(source, "sql_injection")) == 2


def test_sql_static_and_parameterized_query_are_not_reported():
    source = """
cursor.execute("SELECT * FROM users")
user_id = request.args["id"]
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
"""
    assert only_rule(source, "sql_injection") == []


def test_sql_multiple_sinks_and_late_source_are_reported():
    source = "\n".join(["safe = 1"] * 20 + [
        'query = request.json["query"]',
        "cursor.execute(query)",
        "db.executescript(query)",
    ])
    findings = only_rule(source, "sql_injection")
    assert [item["line"] for item in findings] == [22, 23]
    assert all(item["source_line"] == 21 for item in findings)


def test_command_injection_requires_tainted_command_and_shell_for_subprocess():
    source = """
command = request.json["command"]
subprocess.run(command, shell=True)
os.system(command)
subprocess.run(["git", "status"])
subprocess.run(["git", command])
"""
    assert len(only_rule(source, "command_injection")) == 2


def test_static_command_and_non_shell_array_are_not_overclaimed():
    source = """
subprocess.run(["git", "status"])
subprocess.check_output(["git", "status"])
os.system("echo fixed")
"""
    assert only_rule(source, "command_injection") == []


def test_ssrf_requests_httpx_and_urllib():
    source = """
url = request.args.get("url")
requests.get(url)
httpx.post(url)
urllib.request.urlopen(url)
requests.get("https://example.com")
"""
    assert len(only_rule(source, "ssrf")) == 3


def test_static_url_is_not_ssrf():
    assert only_rule('requests.get("https://example.com")', "ssrf") == []


def test_xss_mark_safe_and_markup_require_tainted_html():
    source = """
html = request.args["html"]
return mark_safe(html)
return Markup(html)
return mark_safe("<b>fixed</b>")
"""
    assert len(only_rule(source, "xss_unsafe_html_sink")) == 2


def test_local_function_return_propagates_taint():
    source = """
def build_query(value):
    return "SELECT * FROM users WHERE id=" + value

def route(request):
    user_id = request.args["id"]
    query = build_query(user_id)
    db.execute(query)
"""
    findings = only_rule(source, "sql_injection")
    assert len(findings) == 1
    assert findings[0]["source_line"] == 6


def test_local_sanitized_return_is_not_tainted():
    source = """
def build_query(value):
    return sanitize_sql(value)

def route(request):
    user_id = request.args["id"]
    query = build_query(user_id)
    db.execute(query)
"""
    assert only_rule(source, "sql_injection") == []


def test_named_validator_guard_blocks_following_sink():
    source = """
def route(request):
    url = request.args["url"]
    if not is_allowed_url(url):
        return
    requests.get(url)
"""
    assert only_rule(source, "ssrf") == []


def test_assignment_sanitizers_block_flow():
    source = """
def route(request):
    html = request.args["html"]
    safe_html = escape_html(html)
    return mark_safe(safe_html)
"""
    assert only_rule(source, "xss_unsafe_html_sink") == []


def test_async_class_and_nested_scope_are_supported():
    source = """
class Handler:
    async def route(self, request):
        value = request.body["value"]
        query = f"SELECT {value}"
        self.db.execute(query)

def other(request):
    value = "constant"
    db.execute(value)
"""
    findings = only_rule(source, "sql_injection")
    assert len(findings) == 1
    assert findings[0]["line"] == 6


def test_overwrite_with_static_value_clears_taint():
    source = """
value = request.args["id"]
value = "safe"
db.execute(value)
"""
    assert only_rule(source, "sql_injection") == []


def test_comments_docstrings_and_unrelated_objects_do_not_create_taint():
    source = '''
"""request.args["id"] then subprocess.run(value)"""
class RequestLike:
    args = {"id": "constant"}

obj = RequestLike()
value = obj.args["id"]
db.execute(value)
# requests.get(request.args["url"])
'''
    assert rules(source) == []


def test_malformed_python_is_safe():
    assert analyze_python_taint("broken.py", "def broken(:\n  pass") == []


def test_repeated_analysis_is_stable():
    source = 'db.execute(request.args["id"])'
    assert analyze_python_taint("app.py", source) == analyze_python_taint("app.py", source)


def test_analyzer_integration_emits_taint_finding_and_metadata():
    project = {
        "files": [{"path": "routes.py", "language": "python", "content": 'db.execute(request.args["id"])'}],
        "imports": [], "functions": [], "classes": [], "apiEndpoints": [], "tests": [],
        "configs": [], "deploymentFiles": [], "findings": [], "warnings": [], "structuralMetadata": [],
    }
    analyzed = analyze_project(project)
    findings = [item for item in analyzed["findings"] if item["rule"] == "sql_injection"]
    assert len(findings) == 1
    assert findings[0]["evidence_type"] == "ast_source_sink"


def test_analyzer_prefers_ast_evidence_over_regex_sql_duplicate():
    project = {
        "files": [{
            "path": "routes.py",
            "language": "python",
            "content": 'user_id = request.args["id"]\nquery = "SELECT " + user_id\ncursor.execute(query)',
        }],
        "imports": [], "functions": [], "classes": [], "apiEndpoints": [], "tests": [],
        "configs": [], "deploymentFiles": [], "findings": [], "warnings": [], "structuralMetadata": [],
    }
    findings = analyze_project(project)["findings"]
    security = [item for item in findings if item["rule"] in {"sql_injection", "sql_concat"}]
    assert len(security) == 1
    assert security[0]["rule"] == "sql_injection"
    assert security[0]["evidence_type"] == "ast_source_sink"


def test_ast_reuse_path_is_accepted():
    source = 'db.execute(request.args["id"])'
    tree = ast.parse(source)
    assert len(analyze_python_taint("app.py", source, tree)) == 1
