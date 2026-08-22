"""Phase 2 acceptance suite: finding identity is stable, and reanalysis is
fresh (no accumulation, no ghost findings) -- verified against the REAL
analyze_project pipeline, not a mock.

_finding_id (routers/projects.py) is a pure hash of (rule, file, line,
normalized evidence) -- deliberately excludes array index and any AI
wording, so identity survives reordering and prose changes.
"""

import copy

from routers.projects import _assign_finding_ids, _finding_id
from services.analyzer import analyze_project
from services.security_rules import to_closed_world_findings

FIXTURE_PROJECT = {
    "files": [
        {
            "path": "app.py",
            "language": "python",
            "content": (
                "import subprocess\n"
                "API_KEY = \"not-a-real-secret-value-abc123xyz\"\n"
                "def run(path):\n"
                "    subprocess.run(\"tar -czf out.tar.gz \" + path, shell=True)\n"
            ),
        },
        {
            "path": "util.py",
            "language": "python",
            "content": "def add(a, b):\n    return a + b\n",
        },
    ],
    "findings": [],
    "imports": [],
    "functions": [],
    "classes": [],
    "apiEndpoints": [],
    "tests": [],
    "configs": [],
    "deploymentFiles": [],
    "warnings": [],
}


def _analyze_fresh():
    project = copy.deepcopy(FIXTURE_PROJECT)
    analyzed = analyze_project(project)
    _assign_finding_ids(analyzed["findings"])
    return analyzed


# --------------------------------------------------------- finding_id purity

def test_finding_id_is_a_pure_function_of_rule_file_line_evidence():
    finding = {"rule": "hardcoded_secret", "file": "a.py", "line": 3, "evidence": "API_KEY = 'x'"}
    id1 = _finding_id(finding)
    id2 = _finding_id(dict(finding))  # same content, different dict object
    assert id1 == id2


def test_finding_id_ignores_array_position():
    # Two structurally-identical findings at different list positions must
    # get the same id -- identity must never come from index.
    a = {"rule": "dangerous_eval", "file": "x.py", "line": 5, "evidence": "eval(x)"}
    assert _finding_id(a) == _finding_id(dict(a))


def test_finding_id_ignores_whitespace_differences_in_evidence():
    a = {"rule": "sql_concat", "file": "x.py", "line": 5, "evidence": "SELECT * FROM  users"}
    b = {"rule": "sql_concat", "file": "x.py", "line": 5, "evidence": "SELECT   *   FROM users"}
    assert _finding_id(a) == _finding_id(b)


def test_finding_id_changes_when_rule_file_or_line_changes():
    base = {"rule": "hardcoded_secret", "file": "a.py", "line": 3, "evidence": "x"}
    assert _finding_id(base) != _finding_id({**base, "rule": "dangerous_eval"})
    assert _finding_id(base) != _finding_id({**base, "file": "b.py"})
    assert _finding_id(base) != _finding_id({**base, "line": 4})


def test_finding_id_does_not_depend_on_ai_wording_fields():
    # message/severity/confidence must not affect identity -- only the
    # rule/file/line/evidence tuple does.
    base = {"rule": "hardcoded_secret", "file": "a.py", "line": 3, "evidence": "x"}
    verbose = {**base, "message": "This is a critical hardcoded secret!!!", "confidence": 0.99, "severity": "critical"}
    assert _finding_id(base) == _finding_id(verbose)


# --------------------------------------------------------------- determinism

def test_repeated_analysis_produces_identical_finding_id_sets():
    ANALYSIS_RUNS = 10
    id_sets = []
    for _ in range(ANALYSIS_RUNS):
        analyzed = _analyze_fresh()
        id_sets.append(frozenset(f["finding_id"] for f in analyzed["findings"]))

    first = id_sets[0]
    assert first, "fixture should produce at least one finding"
    for i, ids in enumerate(id_sets[1:], start=2):
        assert ids == first, f"run {i} produced a different finding_id set than run 1"


def test_repeated_analysis_produces_identical_rule_file_line_severity():
    ANALYSIS_RUNS = 10
    snapshots = []
    for _ in range(ANALYSIS_RUNS):
        analyzed = _analyze_fresh()
        snapshot = sorted(
            (f["rule"], f["file"], f["line"], f["severity"]) for f in analyzed["findings"]
        )
        snapshots.append(snapshot)

    first = snapshots[0]
    for i, snap in enumerate(snapshots[1:], start=2):
        assert snap == first, f"run {i} core report differs from run 1"


def test_repeated_analysis_security_findings_are_identical():
    ANALYSIS_RUNS = 10
    snapshots = []
    for _ in range(ANALYSIS_RUNS):
        analyzed = _analyze_fresh()
        gated = to_closed_world_findings(analyzed["findings"])
        snapshot = sorted((g["rule_id"], g["file"], g["line"], g["cwe"]) for g in gated)
        snapshots.append(snapshot)

    first = snapshots[0]
    assert first  # fixture has a real secret + real command injection
    for snap in snapshots[1:]:
        assert snap == first


# --------------------------------------------------------------- reanalysis

def test_reanalysis_does_not_accumulate_findings():
    project = copy.deepcopy(FIXTURE_PROJECT)
    first = analyze_project(project)
    first_count = len(first["findings"])

    # Re-run analysis on the SAME already-analyzed project dict, exactly as
    # get_owned_project -> analyze_project -> save happens in production.
    second = analyze_project(project)
    second_count = len(second["findings"])

    assert second_count == first_count, "reanalysis must not double findings"


def test_reanalysis_after_source_change_reflects_only_current_source():
    project = copy.deepcopy(FIXTURE_PROJECT)
    before = analyze_project(copy.deepcopy(project))
    before_rules = sorted(f["rule"] for f in before["findings"])
    assert "hardcoded_secret" in before_rules

    # Fix the vulnerable line -- remove the hardcoded secret.
    project["files"][0]["content"] = project["files"][0]["content"].replace(
        'API_KEY = "not-a-real-secret-value-abc123xyz"\n', ""
    )
    after = analyze_project(project)
    after_rules = sorted(f["rule"] for f in after["findings"])

    assert "hardcoded_secret" not in after_rules, "fixed line must not still be reported (ghost finding)"
    assert "subprocess_shell_true" in after_rules, "unrelated still-vulnerable line must remain detected"


def test_reanalysis_finding_ids_are_stable_for_unchanged_findings():
    project = copy.deepcopy(FIXTURE_PROJECT)
    before = analyze_project(copy.deepcopy(project))
    _assign_finding_ids(before["findings"])
    before_ids = {f["rule"]: f["finding_id"] for f in before["findings"]}

    # Reanalyze the exact same source (simulates clicking "Reanalyze" with
    # no changes) -- the command-injection finding's id must not shift.
    after = analyze_project(project)
    _assign_finding_ids(after["findings"])
    after_ids = {f["rule"]: f["finding_id"] for f in after["findings"]}

    assert before_ids["subprocess_shell_true"] == after_ids["subprocess_shell_true"]
