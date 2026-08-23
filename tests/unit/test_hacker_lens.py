import pytest

from models.schemas import HackerLensReport
from services import hacker_lens
from services.hacker_lens import _build_context, _build_report, _evidence_catalog, _score_label, run_hacker_lens
from services.groq_client import GroqUnavailableError


PROJECT = {
    "files": [
        {
            "path": "app.py",
            "language": "python",
            "content": (
                "from fastapi import FastAPI, Request\n"
                "app = FastAPI()\n\n"
                "@app.post('/login')\n"
                "def login(request: Request):\n"
                "    return authenticate(request)\n"
            ),
        },
        {
            "path": "utils.py",
            "language": "python",
            "content": "def add(a, b):\n    return a + b\n",
        },
        {
            "path": "README.md",
            "language": "other",
            "content": "# Demo project\n",
        },
    ]
}


def _fake_hydrate(monkeypatch, content_by_path=None):
    """Patches hacker_lens.hydrate_selected_files (the db.mongo function this
    module now calls) with a fake that records the paths it was asked to
    hydrate and never touches real GridFS. Existing PROJECT fixtures already
    carry "content" inline, so the fake only backfills from content_by_path
    for entries that don't already have it -- letting tests that start from
    metadata-only files (no inline "content") prove selective hydration
    actually populates the right ones.
    """
    content_by_path = content_by_path or {}
    calls = []

    async def fake(files, paths=None, max_concurrency=12):
        calls.append(None if paths is None else set(paths))
        for entry in files:
            if entry.get("content") is not None:
                continue
            if paths is not None and entry.get("path") not in paths:
                continue
            source = content_by_path.get(entry.get("path"))
            if source is not None:
                entry["content"] = source

    monkeypatch.setattr(hacker_lens, "hydrate_selected_files", fake)
    return calls


@pytest.fixture(autouse=True)
def hydrate_calls(monkeypatch):
    return _fake_hydrate(monkeypatch)


@pytest.mark.asyncio
async def test_build_context_only_includes_eligible_source_files(hydrate_calls):
    context, included = await _build_context(PROJECT)
    assert included == ["app.py", "utils.py"]
    assert "README.md" not in context
    assert "app.py" in context
    # Selection picked the paths before hydrate_selected_files ran -- the one
    # call it made only asked for the two eligible files, never README.md.
    assert hydrate_calls == [{"app.py", "utils.py"}]


def test_score_label_thresholds_are_fixed_not_model_controlled():
    assert _score_label(0) == "low"
    assert _score_label(3.4) == "low"
    assert _score_label(3.5) == "medium"
    assert _score_label(6.5) == "high"
    assert _score_label(8.5) == "critical"
    assert _score_label(10) == "critical"


def test_build_report_drops_evidence_for_files_not_in_project():
    raw = {
        "summary": "This app exposes an unauthenticated login endpoint.",
        "attack_surface_score": 7,
        "score_reasoning": "Auth endpoint reachable with no visible validation.",
        "top_targets": [
            {"rank": 1, "title": "Login endpoint", "reason": "Handles auth", "evidence": [{"file": "app.py", "line": 4}]}
        ],
        "attack_surfaces": ["Authentication"],
        "risk_paths": [{"label": "Login path", "steps": ["External Input", "POST /login"], "evidence": []}],
        "adversarial_observations": [
            {
                "title": "Unauthenticated login handler",
                "risk": "high",
                "reason": "No credential check visible in the shown context.",
                "evidence": [
                    {"file": "app.py", "line": 5, "function": "login", "route": "/login"},
                    {"file": "totally_made_up_file.py", "line": 99},
                ],
                "potential_impact": "Account takeover",
                "hardening_action": "Add credential verification before returning.",
            }
        ],
        "hacker_hypotheses": [],
        "hardening_priorities": ["Add authentication check to /login"],
    }

    report = _build_report(raw, {"app.py", "utils.py"}, ["app.py", "utils.py"], _evidence_catalog(PROJECT, {"app.py", "utils.py"}))

    assert isinstance(report, HackerLensReport)
    assert report.attack_surface_score == 7
    assert report.attack_surface_label == "high"
    obs = report.adversarial_observations[0]
    # The real app.py reference survives; the hallucinated file is dropped.
    assert [e.file for e in obs.evidence] == ["app.py"]
    assert obs.verified is True


def test_build_report_strips_fake_function_and_route_evidence():
    raw = {
        "summary": "x",
        "attack_surface_score": 7,
        "adversarial_observations": [
            {
                "title": "Real file but fake symbols",
                "risk": "high",
                "evidence": [
                    {"file": "app.py", "line": 500, "function": "not_a_real_function", "route": "/fake"},
                    {"file": "app.py", "line": 5, "function": "login", "route": "/login"},
                ],
            }
        ],
    }

    report = _build_report(raw, {"app.py"}, ["app.py"], _evidence_catalog(PROJECT, {"app.py"}))
    evidence = report.adversarial_observations[0].evidence

    assert evidence[0].file == "app.py"
    assert evidence[0].line is None
    assert evidence[0].function == ""
    assert evidence[0].route == ""
    assert evidence[1].function == "login"
    assert evidence[1].route == "/login"


def test_evidence_catalog_excludes_files_outside_the_selected_set():
    # app.py is the "selected/hydrated" file for this call; utils.py is a
    # real project file but was never shown to the model here -- the catalog
    # must not let a citation borrow utils.py's real add() function just
    # because utils.py happens to exist somewhere in the project.
    catalog = _evidence_catalog(PROJECT, {"app.py"})
    assert "app.py" in catalog
    assert "utils.py" not in catalog


def test_build_report_marks_observation_unverified_when_all_evidence_is_fake():
    raw = {
        "summary": "x",
        "attack_surface_score": 2,
        "adversarial_observations": [
            {"title": "Speculative issue", "risk": "low", "evidence": [{"file": "nonexistent.py", "line": 1}]}
        ],
    }
    report = _build_report(raw, {"app.py"}, ["app.py"])
    obs = report.adversarial_observations[0]
    assert obs.evidence == []
    assert obs.verified is False


@pytest.mark.asyncio
async def test_run_hacker_lens_returns_error_report_when_groq_unavailable(monkeypatch):
    async def fail_call_groq(messages, temperature=0.0):
        raise GroqUnavailableError("no keys configured")

    monkeypatch.setattr(hacker_lens, "call_groq", fail_call_groq)

    report = await run_hacker_lens(PROJECT)

    assert isinstance(report, HackerLensReport)
    assert report.error
    assert report.files_analyzed == ["app.py", "utils.py"]
    # Failure must be self-contained: no exception propagates, so a caller
    # (the router) can return this report as a normal 200 with error/retry
    # state, leaving the rest of CODE MASTER AI completely unaffected.


@pytest.mark.asyncio
async def test_run_hacker_lens_with_no_eligible_files_short_circuits():
    report = await run_hacker_lens({"files": [{"path": "README.md", "language": "other", "content": "hi"}]})
    assert report.error == "no_eligible_files"
    assert report.files_analyzed == []


@pytest.mark.asyncio
async def test_select_files_hydrates_only_the_narrow_selected_path_set(monkeypatch):
    """Proves the P0 fix directly: given a project much larger than
    MAX_FILES where only a handful of paths carry an interesting-name
    keyword, hydrate_selected_files must be called once, with a narrow path
    set (not None, not every path in the project) -- selection runs on path
    alone, before any content is fetched, and content is never populated for
    files outside that set.
    """
    interesting = ["auth/login.py", "routers/admin.py", "db/query.py", "config/secrets.py"]
    content_by_path = {}
    files = []
    for name in interesting:
        files.append({"path": name, "language": "python", "content_ref": f"ref-{name}", "size": 500})
        content_by_path[name] = f"def handler():\n    return '{name}'\n"
    for i in range(36):
        path = f"pkg/module_{i}.py"
        files.append({"path": path, "language": "python", "content_ref": f"ref-{path}", "size": 50 + i})
        content_by_path[path] = f"def util_{i}():\n    return {i}\n"
    project = {"files": files}

    calls = _fake_hydrate(monkeypatch, content_by_path)

    _context, included = await _build_context(project)

    assert len(calls) == 1
    called_paths = calls[0]
    all_paths = {f["path"] for f in files}
    assert called_paths is not None
    assert called_paths < all_paths  # strictly narrower than the whole project
    assert len(called_paths) <= hacker_lens.MAX_FILES
    assert set(interesting) <= called_paths
    assert set(included) == called_paths
    # Nothing outside the selected set was ever populated with content.
    for entry in files:
        if entry["path"] not in called_paths:
            assert entry.get("content") is None
