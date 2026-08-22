from dataclasses import dataclass

from services.analyzers.rules import run_rules


@dataclass
class CorpusCase:
    name: str
    language: str
    code: str
    should_report: bool
    expected_rules: set[str]


CORPUS = [
    CorpusCase("hardcoded_secret", "python", "password = 'real-secret-value'", True, {"hardcoded_secret"}),
    CorpusCase("eval", "python", "eval(payload)", True, {"dangerous_eval"}),
    # Phase 3.2: GOD spec Rule 2 requires concrete evidence of the full
    # source -> propagation -> unsafe construction -> DATABASE EXECUTION
    # SINK path. The original one-line fixture here (just the f-string,
    # never executed) doesn't show a sink, so it's no longer a valid
    # positive case -- an unexecuted string assignment isn't exploitable
    # by itself. Updated to include the cursor.execute() sink the rule
    # now correctly requires before firing.
    CorpusCase(
        "sql_concat", "python",
        "query = f\"SELECT * FROM users WHERE id = {user_id}\"\ncursor.execute(query)",
        True, {"sql_concat"},
    ),
    CorpusCase("subprocess_shell", "python", "subprocess.run(cmd, shell=True)", True, {"subprocess_shell_true"}),
    CorpusCase("pickle", "python", "pickle.loads(blob)", True, {"unsafe_deserialization"}),
    CorpusCase("yaml", "python", "yaml.load(body)", True, {"unsafe_deserialization"}),
    CorpusCase("ssrf", "python", "requests.get(request.args['url'])", True, {"ssrf_untrusted_url"}),
    CorpusCase("cors", "python", "CORSMiddleware(app, allow_origins=['*'])", True, {"permissive_cors"}),
    CorpusCase("weak_hash", "python", "password_hash = hashlib.md5(password).hexdigest()", True, {"weak_crypto_hash"}),
    CorpusCase("redirect", "python", "return redirect(request.args['next'])", True, {"unsafe_redirect"}),
    CorpusCase("comment_secret", "python", "# password = 'example-secret'", False, set()),
    CorpusCase("doc_secret", "python", "text = \"example password = 'fake-value'\"", False, set()),
    CorpusCase("static_url", "python", "requests.get('https://api.example.com/health')", False, set()),
    CorpusCase("safe_sql", "python", "cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))", False, set()),
    CorpusCase("safe_yaml", "python", "yaml.load(body, Loader=yaml.SafeLoader)", False, set()),
    CorpusCase("safe_subprocess_args", "python", "subprocess.run(['ls', '-la'], shell=False)", False, set()),
    CorpusCase("safe_cors", "python", "CORSMiddleware(app, allow_origins=['https://example.com'])", False, set()),
    CorpusCase("safe_hash_context", "python", "checksum = hashlib.md5(file_bytes).hexdigest()", False, set()),
    CorpusCase("test_fixture_secret", "python", "# test fixture\napi_key = 'fake-key-for-tests'", False, set()),
    CorpusCase("docs_eval", "python", "docs = 'avoid eval(payload) in production'", False, set()),
    CorpusCase("tail_secret", "python", "\n".join(["x = 1"] * 1000 + ["token = 'tail-secret-value'"]), True, {"hardcoded_secret"}),
    CorpusCase("large_comment_then_eval", "python", "\n".join(["# filler"] * 1000 + ["exec(payload)"]), True, {"dangerous_eval"}),
    CorpusCase("async_sleep", "python", "async def h():\n    time.sleep(1)", True, {"blocking_call_in_async"}),
    CorpusCase("tempfile", "python", "name = tempfile.mktemp()", True, {"unsafe_tempfile"}),
    CorpusCase("debug", "python", "app.run(debug=True)", True, {"debug_config_enabled"}),
    CorpusCase("sensitive_log", "python", "logger.info('password=%s', password)", True, {"sensitive_logging"}),
    CorpusCase("frontend_token", "javascript", "localStorage.setItem('jwt_token', token)", True, {"frontend_token_storage"}),
    CorpusCase("xss", "javascript", "el.innerHTML = req.body.name", True, {"xss_unsafe_html_sink"}),
    CorpusCase("safe_literal_innerhtml", "javascript", "el.innerHTML = '<strong>ok</strong>'", False, set()),
    CorpusCase("math_random_non_secret", "javascript", "const n = Math.random() * 10", False, set()),
]


def test_phase1_security_corpus_precision_recall():
    true_positive = false_positive = false_negative = 0
    for case in CORPUS:
        findings = run_rules(f"{case.name}.py", case.language, case.code)
        rules = {finding["rule"] for finding in findings}
        matched = bool(case.expected_rules & rules)
        reported = bool(findings)
        if case.should_report and matched:
            true_positive += 1
        elif case.should_report and not matched:
            false_negative += 1
        elif not case.should_report and reported:
            false_positive += 1

    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    f1 = 2 * precision * recall / (precision + recall)
    false_positive_rate = false_positive / len([case for case in CORPUS if not case.should_report])

    assert true_positive == len([case for case in CORPUS if case.should_report])
    assert false_negative == 0
    assert false_positive <= 1
    assert precision >= 0.94
    assert recall == 1.0
    assert f1 >= 0.97
    assert false_positive_rate <= 0.08
