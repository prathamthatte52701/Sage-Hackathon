from services.analyzer import analyze_project
from services.analyzer import analyze_project
from services.analyzers.rules import RULE_METADATA, run_rules
from services.security_rules import to_closed_world_findings


def test_hardcoded_secret_true_positive():
    findings = run_rules("app.py", "python", "API_KEY = 'abcdef12345'\n")
    assert any(f["rule"] == "hardcoded_secret" for f in findings)


def _analyze_security_rules(code: str) -> list[str]:
    project = {
        "files": [{"path": "app.py", "language": "python", "content": code}],
    }
    analyzed = analyze_project(project)
    gated = to_closed_world_findings(analyzed["findings"])
    return [finding["rule_id"] for finding in gated]


def test_taint_command_injection_survives_dedup_and_closed_world_gate():
    code = "cmd = request.args['cmd']\nsubprocess.run(cmd, shell=True)\n"

    assert _analyze_security_rules(code) == ["SEC-COMMAND-INJECTION"]


def test_taint_ssrf_survives_dedup_and_closed_world_gate():
    code = "url = request.args['url']\nrequests.get(url)\n"

    assert _analyze_security_rules(code) == ["SEC-SSRF"]


def test_overlapping_command_detector_and_taint_result_dedupes_to_one_canonical_finding():
    code = "cmd = request.args['cmd']\nsubprocess.run(cmd, shell=True)\n"

    assert _analyze_security_rules(code).count("SEC-COMMAND-INJECTION") == 1


def test_hardcoded_secret_ignores_comment_and_fake_example():
    content = """
# API_KEY = 'abcdef12345'
example_secret = 'abcdef12345'
"""
    findings = run_rules("README.py", "python", content)
    assert not any(f["rule"] == "hardcoded_secret" for f in findings)


def _rules(content, language="javascript", path="app.js"):
    return {finding["rule"] for finding in run_rules(path, language, content)}


def test_sql_injection_dedup_merges_regex_and_ast_root_cause():
    # Same underlying vulnerability is independently caught by two detectors:
    # the regex sql_concat rule (deterministic_pattern) sees the f-string SQL
    # construction on its own line, and the AST taint engine sees the full
    # request -> variable -> execute() sink path (ast_source_sink) one line
    # later at the sink itself. Root-cause dedup in analyze_project must
    # collapse these into a single finding and keep the stronger AST evidence
    # -- otherwise the same vulnerability would be reported to the user twice.
    content = (
        "def handler(request):\n"
        '    name = request.args.get("name")\n'
        "    query = f\"SELECT * FROM users WHERE name = '{name}'\"\n"
        "    cursor.execute(query)\n"
    )

    # Sanity: the regex rule really does fire standalone on this content, so
    # the dedup below is proven to be merging two real detections, not just
    # observing that only one ever fired in the first place.
    assert "sql_concat" in _rules(content, language="python", path="app.py")

    project = {"files": [{"path": "app.py", "language": "python", "content": content}]}
    result = analyze_project(project)

    sql_findings = [f for f in result["findings"] if f["rule"] in {"sql_injection", "sql_concat"}]
    assert len(sql_findings) == 1, f"expected the two detections to merge into one, got {sql_findings}"
    assert sql_findings[0]["evidence_type"] == "ast_source_sink", "the stronger source-to-sink evidence must win the merge"


def test_rule_metadata_has_stable_entries_for_all_current_rules():
    assert len(RULE_METADATA) >= 28
    for rule_id, meta in RULE_METADATA.items():
        assert rule_id
        assert meta["title"]
        assert meta["category"]
        assert meta["languages"]


def test_python_security_detectors_positive_cases():
    content = """
import os, tempfile, random, hashlib, requests, time
from fastapi import Request

DEBUG = True

async def handler():
    time.sleep(1)

def route(request: Request):
    token = str(random.random())
    password = request.json
    digest = hashlib.md5(password.encode()).hexdigest()
    os.system(request.json["cmd"])
    requests.get(request.args["url"])
    redirect(request.args["next"])
    tempfile.mktemp()
    logger.info("password=%s", password)
"""
    rules = _rules(content, "python", "app.py")
    expected = {
        "debug_config_enabled",
        "blocking_call_in_async",
        "insecure_random_secret",
        "plaintext_password_handling",
        "weak_crypto_hash",
        "os_system_call",
        "ssrf_untrusted_url",
        "unsafe_redirect",
        "unsafe_tempfile",
        "sensitive_logging",
    }
    assert expected <= rules


def test_python_language_filter_does_not_emit_js_specific_rules():
    rules = _rules("localStorage.setItem('token', token)\nNumber(value) || 0", "python", "app.py")
    assert "frontend_token_storage" not in rules
    assert "js_numeric_coercion_default" not in rules


def test_javascript_security_detectors_positive_cases():
    content = """
const crypto = require('crypto');
const child_process = require('child_process');
    app.use(cors({ origin: '*', credentials: true }));
const DEBUG = 'development';
async function handler(req, res) {
  child_process.spawn('sh', ['-c', req.body.cmd], { shell: true });
  child_process.execSync(req.body.cmd);
  axios.get(req.query.url);
  User.find(req.body);
  document.body.innerHTML = req.body.html;
  res.redirect(req.query.next);
  localStorage.setItem('token', token);
  console.log(req.body.password);
  const token = Math.random().toString();
  const digest = crypto.createHash('sha1').update(token).digest('hex');
  const password = req.body.password;
}
"""
    rules = _rules(content)
    expected = {
        "spawn_shell_true",
        "blocking_call_in_async",
        "ssrf_untrusted_url",
        "nosql_untrusted_filter",
        "xss_unsafe_html_sink",
        "unsafe_redirect",
        "frontend_token_storage",
        "sensitive_logging",
        "insecure_random_secret",
        "weak_crypto_hash",
        "plaintext_password_handling",
        "permissive_cors",
        "debug_config_enabled",
    }
    assert expected <= rules


def test_javascript_correctness_transaction_fixture_detectors():
    content = """
export function summarizeTransactions(transactions) {
  return transactions.reduce((summary, tx) => {
    const amount = Number(tx.amount) || 0;
    if (tx.type === "credit") {
      summary.income += amount;
    } else {
      summary.expense += amount;
    }
    summary.byDay[tx.date.slice(0, 10)] = amount;
    return summary;
  }, { income: 0, expense: 0, byDay: {} });
}

export function percentageChange(current, previous) {
  if (!previous) return 0;
  return ((current - previous) / previous) * 100;
}
"""
    rules = _rules(content)
    assert {
        "js_numeric_coercion_default",
        "js_date_slice_without_validation",
        "js_zero_baseline_fallback",
        "js_unknown_type_default",
    } <= rules
    assert not any(rule.startswith("sql") or rule.startswith("xss") for rule in rules)


def test_javascript_month_component_range_without_validation_is_reported():
    content = """
function monthKey(monthYear) {
  const [year, month] = monthYear.split('-').map(Number);
  return new Date(year, month, 1);
}
"""
    rules = _rules(content)

    assert "js_date_component_range_without_validation" in rules


def test_javascript_correctness_safe_patterns_do_not_fire():
    content = """
const parsed = Number(value);
if (Number.isNaN(parsed)) throw new Error('invalid amount');
const day = new Date(tx.date);
if (Number.isNaN(day.getTime())) throw new Error('invalid date');
switch (tx.type) {
  case 'credit': summary.income += parsed; break;
  case 'debit': summary.expense += parsed; break;
  default: throw new Error('unknown type');
}
if (previous === 0) return null;
"""
    rules = _rules(content)
    assert "js_numeric_coercion_default" not in rules
    assert "js_date_slice_without_validation" not in rules
    assert "js_zero_baseline_fallback" not in rules
    assert "js_unknown_type_default" not in rules


def test_security_context_guards_reduce_false_positives():
    rules = _rules("const color = Math.random(); const checksum = crypto.createHash('md5');")
    assert "insecure_random_secret" not in rules
    assert "weak_crypto_hash" not in rules


def test_javascript_route_and_function_extraction():
    project = {
        "files": [
            {
                "path": "routes/users.js",
                "language": "javascript",
                "content": "const createUser = async (req, res) => res.send('ok');\nrouter.post('/users', createUser)",
            }
        ],
        "imports": [],
        "functions": [],
        "classes": [],
        "apiEndpoints": [],
        "tests": [],
        "configs": [],
        "deploymentFiles": [],
        "findings": [],
        "warnings": [],
    }
    analyzed = analyze_project(project)
    assert {"file": "routes/users.js", "name": "createUser"} in analyzed["functions"]
    assert analyzed["apiEndpoints"][0]["method"] == "POST"
    assert analyzed["apiEndpoints"][0]["path"] == "/users"


def test_python_fastapi_route_extraction():
    project = {
        "files": [
            {
                "path": "main.py",
                "language": "python",
                "content": "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health():\n    return {'ok': True}\n",
            }
        ],
        "imports": [],
        "functions": [],
        "classes": [],
        "apiEndpoints": [],
        "tests": [],
        "configs": [],
        "deploymentFiles": [],
        "findings": [],
        "warnings": [],
    }
    analyzed = analyze_project(project)
    assert analyzed["apiEndpoints"][0]["method"] == "GET"
    assert analyzed["apiEndpoints"][0]["path"] == "/health"
    assert analyzed["apiEndpoints"][0]["handler"] == "health"
