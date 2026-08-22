"""Adversarial QA for the deliberately small Phase 2 taint engine."""

import time

import pytest

from services.analyzers.python_taint import analyze_python_taint


def _rules(source: str) -> set[str]:
    return {item["rule"] for item in analyze_python_taint("phase25.py", source)}


TRUE_POSITIVES = [
    ("sql", 'x=request.args["x"]\ny=x\nz=y\ndb.execute(z)'),
    ("sql", 'x=request.args["x"]\ndb.execute("SELECT " + x)'),
    ("sql", 'x=request.args["x"]\ndb.execute(f"SELECT {x}")'),
    ("sql", 'a=request.args["a"]\nb=request.args["b"]\ndb.execute(a)\ndb.execute(b)'),
    ("sql", 'x="safe"\nx=request.args["x"]\ndb.execute(x)'),
    ("sql", 'x=request.args["x"]\nif condition:\n    x=x\ndb.execute(x)'),
    ("sql", 'x=request.args["x"]\nif condition:\n    x=sanitize(x)\nelse:\n    x=x\ndb.execute(x)'),
    ("sql", 'def one(x):\n return "SELECT " + x\ndef two(x):\n return one(x)\nx=request.args["x"]\ndb.execute(two(x))'),
    ("sql", 'def one(x):\n return "SELECT " + x\ndef two(x):\n return one(x)\ndef three(x):\n return two(x)\nx=request.args["x"]\ndb.execute(three(x))'),
    ("sql", 'def build_query(value):\n return "SELECT " + value\ndef route(request):\n value=request.args["id"]\n query=build_query(value)\n db.execute(query)'),
    ("sql", 'class C:\n def route(self, request):\n  x=request.args["x"]\n  self.db.execute(x)'),
    ("sql", 'async def route(request):\n x=request.json["x"]\n db.execute(x)'),
    ("sql", 'x=request.args["x"]\ndata={"x":x}\ndb.execute(data["x"])'),
    ("sql", 'x=request.args["x"]\ndata=[x]\ndb.execute(data[0])'),
    ("sql", 'x=request.args["x"]\ndata=(x,)\ndb.execute(data[0])'),
    ("sql", 'x=request.args["x"]\ndb.execute(x)\ndb.executemany(x)'),
    ("sql", 'x=request.args["x"]\ndb.execute(x)\ndb.executescript(x)'),
    ("sql", 'x=request.args["x"]\nif valid:\n x=sanitize(x)\ndb.execute(x)'),
    ("sql", 'def sanitize_fake(x):\n return x\nx=request.args["x"]\nx=sanitize_fake(x)\ndb.execute(x)'),
    ("sql", 'req=request\nx=req.args["x"]\ndb.execute(x)'),
    ("sql", 'def route(req):\n x=req.query["x"]\n db.execute(x)'),
    ("sql", 'x=request.args.get("x")\ndb.execute(x, params)'),
    ("sql", 'x=request.args["x"]; db.execute(x)'),
    ("command_injection", 'x=request.json["cmd"]\nos.system(x)'),
    ("command_injection", 'x=request.json["cmd"]\nos.popen(x)'),
    ("command_injection", 'x=request.json["cmd"]\nsubprocess.run(x, shell=True)'),
    ("command_injection", 'x=request.json["cmd"]\nsubprocess.Popen(x, shell=True)'),
    ("command_injection", 'x=request.json["cmd"]\nsubprocess.check_output(x, shell=True)'),
    ("ssrf", 'x=request.args["url"]\nrequests.get(x)'),
    ("ssrf", 'x=request.args["url"]\nhttpx.request("GET", x)'),
    ("ssrf", 'x=request.args["url"]\nurllib.request.urlopen(x)'),
    ("ssrf", 'x=request.args["url"]\ndata={"url":x}\nrequests.get(data["url"])'),
    ("ssrf", 'x=request.args["url"]\nif valid:\n x=sanitize(x)\nelse:\n x=x\nrequests.get(x)'),
    ("xss_unsafe_html_sink", 'x=request.args["html"]\nmark_safe(x)'),
    ("xss_unsafe_html_sink", 'x=request.args["html"]\nMarkup(x)'),
    ("xss_unsafe_html_sink", 'class C:\n def route(self, request):\n  x=request.body["html"]\n  return mark_safe(x)'),
    ("xss_unsafe_html_sink", 'async def route(request):\n x=request.form["html"]\n return Markup(x)'),
    ("xss_unsafe_html_sink", 'x=request.args["html"]\nreturn mark_safe("<b>" + x)'),
    ("xss_unsafe_html_sink", 'def render(x):\n return Markup(x)\nx=request.args["html"]\nrender(x)'),
    ("ssrf", 'x=request.args["url"]\nrequests.get(x)\nrequests.post(x)'),
    ("sql", 'x=request.args["x"]\nfor item in [x]:\n db.execute(item)'),
]


TRUE_RULES = {"sql", "command_injection", "ssrf", "xss_unsafe_html_sink"}
EXPECTED_RULES = {
    "sql": "sql_injection",
    "command_injection": "command_injection",
    "ssrf": "ssrf",
    "xss_unsafe_html_sink": "xss_unsafe_html_sink",
}


TRUE_NEGATIVES = [
    'db.execute("SELECT * FROM users")',
    'db.execute("SELECT * FROM users WHERE id=?", (request.args["id"],))',
    'db.execute("SELECT * FROM users WHERE id=%s", params)',
    'subprocess.run(["git", "status"])',
    'subprocess.run(["git", request.args["arg"]])',
    'subprocess.Popen(["git", "status"])',
    'os.system("echo fixed")',
    'requests.get("https://example.com")',
    'httpx.get("https://example.com")',
    'urllib.request.urlopen("https://example.com")',
    'mark_safe("<b>fixed</b>")',
    'Markup("<b>fixed</b>")',
    'x="safe"\ndb.execute(x)',
    'x=request.args["x"]\nx="safe"\ndb.execute(x)',
    'x=request.args["url"]\nx=sanitize_url(x)\nrequests.get(x)',
    'x=request.args["url"]\nif not is_allowed_url(x):\n return\nrequests.get(x)',
    'x=request.args["html"]\nx=escape_html(x)\nmark_safe(x)',
    'def sanitize_html(x):\n return escape(x)\nx=request.args["x"]\ndb.execute(sanitize_html(x))',
    'def unrelated(value):\n db.execute(value)',
    'def route(request):\n x="safe"\n db.execute(x)',
    'obj.args["x"]\ndb.execute("fixed")',
    '# request.args["x"]\n# db.execute(x)',
    '"request.args[\\"x\\"] then db.execute(x)"',
    '"""requests.get(request.args[\'url\'])"""',
    '"SELECT " + "constant"',
    'url="https://example.com"\nrequests.get(url)',
    'x=request.args["x"]\nlog(x)\ndb.execute("fixed")',
    'if condition:\n x=request.args["x"]\nelse:\n x="safe"\ndb.execute("fixed")',
    'if condition:\n x=request.args["x"]\nelse:\n x="safe"\ndb.execute("SELECT fixed")',
    'x=request.args["x"]\nif condition:\n x=sanitize(x)\ndb.execute("fixed")',
    'def build(x):\n return sanitize(x)\nx=request.args["x"]\ndb.execute("fixed")',
    'request = object()\nx=request.args["x"]\ndb.execute("fixed")',
    'req = object()\nx=req.args["x"]\ndb.execute("fixed")',
    'class Docs:\n text="subprocess.run(request.args[\\"cmd\\"], shell=True)"',
    'def f(request):\n """db.execute(request.args[\\"x\\"])"""\n return "fixed"',
    'x=request.args["x"]\nvalue={"x": "fixed"}\ndb.execute(value["x"])',
]


@pytest.mark.parametrize("expected,source", TRUE_POSITIVES)
def test_adversarial_true_positive(expected, source):
    rules = _rules(source)
    assert EXPECTED_RULES[expected] in rules, (expected, rules, source)


@pytest.mark.parametrize("source", TRUE_NEGATIVES)
def test_adversarial_true_negative(source):
    assert _rules(source) == set(), source


def test_adversarial_case_count_and_metric_shape():
    assert len(TRUE_POSITIVES) + len(TRUE_NEGATIVES) >= 75
    tp = sum(EXPECTED_RULES[expected] in _rules(source) for expected, source in TRUE_POSITIVES)
    fp = sum(bool(_rules(source)) for source in TRUE_NEGATIVES)
    fn = len(TRUE_POSITIVES) - tp
    tn = len(TRUE_NEGATIVES) - fp
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    false_positive_rate = fp / (fp + tn) if fp + tn else 0.0
    false_negative_rate = fn / (fn + tp) if fn + tp else 0.0
    assert tp == len(TRUE_POSITIVES)
    assert fp == 0
    assert (precision, recall, f1, false_positive_rate, false_negative_rate) == (1.0, 1.0, 1.0, 0.0, 0.0)


def test_large_file_and_repeatability():
    source = "\n".join(["safe = 1"] * 5000 + ['x=request.args["x"]', "db.execute(x)"])
    started = time.perf_counter()
    first = analyze_python_taint("large.py", source)
    elapsed = time.perf_counter() - started
    second = analyze_python_taint("large.py", source)
    assert first == second
    assert len(first) == 1
    assert first[0]["source_line"] == 5001
    assert elapsed < 2.0


def test_malformed_and_vulnerable_at_file_edges_are_safe():
    assert analyze_python_taint("broken.py", "def broken(:\n pass") == []
    first = analyze_python_taint("first.py", 'db.execute(request.args["x"])')
    last = analyze_python_taint("last.py", 'safe=1\n' * 10 + 'db.execute(request.args["x"])')
    assert first[0]["sink_line"] == 1
    assert last[0]["sink_line"] == 11
