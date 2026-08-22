import pytest

from services.analyzers.python_taint import analyze_python_taint


TRUE_POSITIVES = [
    'db.execute(request.args["id"])',
    'x=request.args["id"]\ndb.execute(x)',
    'x=request.args["id"]\ny=x\ndb.execute(y)',
    'x=request.args["id"]\ndb.execute("SELECT " + x)',
    'x=request.args["id"]\ndb.execute(f"SELECT {x}")',
    'x=request.args.get("id")\ndb.executemany(x)',
    'x=request.json["cmd"]\nsubprocess.run(x, shell=True)',
    'x=request.args["cmd"]\nos.system(x)',
    'x=request.body["cmd"]\nos.popen(x)',
    'x=request.json["url"]\nrequests.get(x)',
    'x=request.query_params.get("url")\nhttpx.post(x)',
    'x=request.query["url"]\nurllib.request.urlopen(x)',
    'x=request.args["html"]\nmark_safe(x)',
    'x=request.form.get("html")\nMarkup(x)',
    'x=request.args["id"]\nquery=build(x)\ndb.execute(query)',
    'x=request.args["id"]\npayload={"id":x}\ndb.execute(payload["id"])',
    'req=request\nx=req.params["id"]\ndb.execute(x)',
    'async def f(request):\n x=request.body["id"]\n db.execute(f"SELECT {x}")',
    'class C:\n def f(self, request):\n  x=request.json["id"]\n  db.execute(x)',
    'x=request.args["id"]; db.execute(x)',
]

TRUE_RULES = [
    "sql_injection", "sql_injection", "sql_injection", "sql_injection", "sql_injection",
    "sql_injection", "command_injection", "command_injection", "command_injection",
    "ssrf", "ssrf", "ssrf", "xss_unsafe_html_sink", "xss_unsafe_html_sink",
    "sql_injection", "sql_injection", "sql_injection", "sql_injection", "sql_injection",
    "sql_injection",
]

FALSE_POSITIVES = [
    'db.execute("SELECT * FROM users")',
    'db.execute("SELECT * FROM users WHERE id=?", (request.args["id"],))',
    'subprocess.run(["git", "status"])',
    'subprocess.run(["git", request.args["arg"]])',
    'subprocess.run(request.args["cmd"])',
    'os.system("echo fixed")',
    'requests.get("https://example.com")',
    'httpx.post("https://example.com")',
    'urllib.request.urlopen("https://example.com")',
    'mark_safe("<b>fixed</b>")',
    'Markup("<b>fixed</b>")',
    'value="constant"\ndb.execute(value)',
    'value=request.args["id"]\nvalue="safe"\ndb.execute(value)',
    'value=request.args["url"]\nvalue=sanitize_url(value)\nrequests.get(value)',
    'value=request.args["url"]\nif not is_allowed_url(value): return\nrequests.get(value)',
    'def f(request):\n return sanitize_sql(request.args["id"])\ndb.execute(f(request))',
    'obj.args["id"]\ndb.execute("fixed")',
    '# request.args["id"]\n# db.execute(value)',
    '"request.args[\\"id\\"] and subprocess.run(value)"',
    'def unrelated(value):\n db.execute(value)',
]


@pytest.mark.parametrize("source,expected", list(zip(TRUE_POSITIVES, TRUE_RULES)))
def test_true_positive_corpus(source, expected):
    assert any(item["rule"] == expected for item in analyze_python_taint("corpus.py", source))


@pytest.mark.parametrize("source", FALSE_POSITIVES)
def test_true_negative_corpus(source):
    assert analyze_python_taint("corpus.py", source) == []


ADVERSARIAL = [
    'request.args["id"]; db.execute(request.args["id"])',
    'x=1\n' * 80 + 'x=request.args["id"]\ndb.execute(x)',
    'class C:\n async def f(self, request):\n  x=request.args["id"]\n  db.execute(x)',
    'x=request.args["id"]\nx="safe"\ndb.execute(x)',
    'def f(request):\n x=request.args["id"]\n return x\ndef g(request):\n x="safe"\n db.execute(x)',
    'req=request\nx=req.json["x"]\ndb.execute(x)',
    'x=request.json["nested"]["value"]\ndb.execute(x)',
    'def build(x):\n return "SELECT " + x\nx=request.args["id"]\ndb.execute(build(x))',
    'x=request.args["id"]\nif not is_valid_id(x):\n return\ndb.execute(x)',
    'x=request.args["id"]\ndb.execute(x)\ndb.execute("fixed")',
]


@pytest.mark.parametrize("source", ADVERSARIAL)
def test_adversarial_corpus_does_not_crash(source):
    findings = analyze_python_taint("adversarial.py", source)
    assert isinstance(findings, list)


def test_corpus_metrics_are_measured_and_stable():
    tp = sum(bool(analyze_python_taint("tp.py", source)) for source in TRUE_POSITIVES)
    fp = sum(bool(analyze_python_taint("fp.py", source)) for source in FALSE_POSITIVES)
    fn = len(TRUE_POSITIVES) - tp
    tn = len(FALSE_POSITIVES) - fp
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    false_positive_rate = fp / (fp + tn) if fp + tn else 0.0
    assert (tp, fn, fp, tn) == (20, 0, 0, 20)
    assert precision == 1.0
    assert recall == 1.0
    assert false_positive_rate == 0.0
