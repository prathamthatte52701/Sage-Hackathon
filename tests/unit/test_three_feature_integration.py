import copy
import io
import json
import zipfile

import pytest
from fastapi import UploadFile

import routers.projects as projects_router
from models.schemas import BrutalAuditReport, HackerLensReport
from services import brutal_audit, hacker_lens
from services.groq_client import GroqUnavailableError


USER = {"_id": "demo-user", "email": "demo@sage.local"}


class FakeProjectStore:
    def __init__(self):
        self.projects: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self._project_counter = 0
        self._job_counter = 0

    async def save_project(self, project: dict, session_id: str, owner_user_id: str) -> str:
        self._project_counter += 1
        project_id = f"three-feature-project-{self._project_counter}"
        doc = copy.deepcopy(project)
        doc.update(
            {
                "_id": project_id,
                "session_id": session_id,
                "owner_user_id": owner_user_id,
                "source_revision": 1,
                "analysis_revision": 0,
                "analysis_status": "not_started",
            }
        )
        self.projects[project_id] = doc
        return project_id

    async def get_owned_project(self, project_id: str, owner_user_id: str):
        doc = self.projects.get(project_id)
        if doc is None or doc.get("owner_user_id") != owner_user_id:
            return None
        return copy.deepcopy(doc)

    async def get_owned_project_metadata(self, project_id: str, owner_user_id: str):
        return await self.get_owned_project(project_id, owner_user_id)

    async def get_owned_project_file(self, project_id: str, owner_user_id: str, path: str):
        project = await self.get_owned_project(project_id, owner_user_id)
        if project is None:
            return None
        return next((entry for entry in project.get("files", []) if entry.get("path") == path), None)

    async def update_owned_project(self, project_id: str, owner_user_id: str, updates: dict, *, expected_source_revision: int | None = None) -> bool:
        doc = self.projects.get(project_id)
        if doc is None or doc.get("owner_user_id") != owner_user_id:
            return False
        if expected_source_revision is not None and doc.get("source_revision") != expected_source_revision:
            return False
        doc.update(copy.deepcopy(updates))
        return True

    async def update_owned_finding(self, project_id: str, owner_user_id: str, finding_id: str, updates: dict) -> bool:
        return False

    async def enqueue_analysis(self, project_id: str, owner_user_id: str, work):
        self._job_counter += 1
        job_id = f"three-feature-job-{self._job_counter}"
        result = await work(job_id)
        job = {
            "_id": job_id,
            "project_id": project_id,
            "owner_user_id": owner_user_id,
            "status": "partial" if result.get("partial") else "completed",
            "result": result,
        }
        self.jobs[job_id] = job
        return copy.deepcopy(job), True

    async def get_owned_analysis_job(self, job_id: str, owner_user_id: str):
        job = self.jobs.get(job_id)
        if job is None or job.get("owner_user_id") != owner_user_id:
            return None
        return copy.deepcopy(job)


@pytest.fixture
def feature_store(monkeypatch):
    store = FakeProjectStore()
    monkeypatch.setattr(projects_router, "save_project", store.save_project)
    monkeypatch.setattr(projects_router, "get_owned_project", store.get_owned_project)
    monkeypatch.setattr(projects_router, "get_owned_project_metadata", store.get_owned_project_metadata)
    monkeypatch.setattr(projects_router, "get_owned_project_file", store.get_owned_project_file)
    monkeypatch.setattr(projects_router, "update_owned_project", store.update_owned_project)
    monkeypatch.setattr(projects_router, "update_owned_finding", store.update_owned_finding)
    monkeypatch.setattr(projects_router, "enqueue_analysis", store.enqueue_analysis)
    monkeypatch.setattr(projects_router, "get_analysis_job_with_recovery", store.get_owned_analysis_job)

    async def no_ai_findings(project: dict) -> dict:
        coverage = {
            "semantic_coverage": "complete",
            "ai_candidate_count": 0,
            "ai_finding_count": 0,
            "ai_chunks_total": 0,
            "ai_chunks_completed": 0,
            "groq_calls": 0,
        }
        project["ai_review_coverage"] = coverage
        return coverage

    monkeypatch.setattr(projects_router, "run_ai_quality_review", no_ai_findings)
    return store


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buffer.getvalue()


FIXTURES = {
    "normal": {
        "filename": "sage_test_01.zip",
        "files": {
            "app.py": """from fastapi import FastAPI, Request
import sqlite3

app = FastAPI()
JWT_SECRET = "eyJhbGciOiJIUzI1NiJ9aB3xQ9mK2pL7vN4wR8tY1uJ6"

@app.get("/user")
def user(request: Request):
    email = request.query_params["email"]
    query = f"SELECT * FROM users WHERE email = '{email}'"
    return sqlite3.connect("app.db").execute(query).fetchall()
""",
        },
    },
    "hacker": {
        "filename": "sage_test_02.zip",
        "files": {
            "app.py": """from fastapi import FastAPI, Request
from pathlib import Path
import requests

app = FastAPI()
REPORT_DIR = Path("/srv/reports")

@app.get("/preview")
def preview(url: str):
    return requests.get(url, timeout=4).text

@app.get("/reports")
def reports(name: str):
    return (REPORT_DIR / name).read_text()

@app.get("/admin/export")
def admin_export(request: Request):
    role = request.headers.get("x-role")
    if role != "admin":
        return {"error": "forbidden"}
    return {"data": "sensitive export"}
""",
        },
    },
    "brutal": {
        "filename": "sage_test_03.zip",
        "files": {
            "app.py": """from fastapi import FastAPI
from pydantic import BaseModel
import requests

app = FastAPI()
CACHE = {}

class ReportRequest(BaseModel):
    user_id: int

def fetch_profile(user_id: int):
    response = requests.get(f"https://internal.example/users/{user_id}")
    response.raise_for_status()
    return response.json()

@app.post("/report")
async def report(payload: ReportRequest):
    if payload.user_id <= 0:
        raise ValueError("user_id must be positive")
    try:
        if payload.user_id not in CACHE:
            CACHE[payload.user_id] = fetch_profile(payload.user_id)
        with open("reports.log", "a", encoding="utf-8") as handle:
            handle.write(str(payload.user_id))
        return {"profile": CACHE[payload.user_id]}
    except Exception:
        return {"error": "failed"}
""",
        },
    },
}


def _hacker_payload(kind: str) -> dict:
    if kind == "normal":
        return {
            "summary": "The public /user route is the adversarially interesting database path.",
            "attack_surface_score": 6.8,
            "score_reasoning": "Public request data reaches user lookup and database code.",
            "top_targets": [
                {"rank": 1, "title": "User lookup route", "reason": "Public input reaches database-sensitive logic.", "evidence": [{"file": "app.py", "line": 7, "function": "user", "route": "GET /user"}]}
            ],
            "attack_surfaces": ["Public input", "Database"],
            "risk_paths": [
                {"label": "User input to database", "steps": ["GET /user", "email query parameter", "SQL execution"], "evidence": [{"file": "app.py", "line": 11, "function": "user", "route": "/user"}]}
            ],
            "adversarial_observations": [
                {"title": "/user exposes a public input to database path", "risk": "high", "reason": "The route reads request-controlled email and executes SQL.", "evidence": [{"file": "app.py", "line": 9, "function": "user", "route": "/user"}], "potential_impact": "Database-sensitive lookup path deserves review.", "hardening_action": "Use parameterized queries and consistent auth controls."}
            ],
            "hacker_hypotheses": [],
            "hardening_priorities": ["Parameterize SQL in the /user path."],
        }
    if kind == "hacker":
        return {
            "summary": "This app exposes multiple attacker-interesting entry points without relying on exploit instructions.",
            "attack_surface_score": 8.0,
            "score_reasoning": "Network, filesystem, and header-based privileged flows are visible.",
            "top_targets": [
                {"rank": 1, "title": "Preview fetch", "reason": "Caller supplies the outbound URL.", "evidence": [{"file": "app.py", "line": 8, "function": "preview", "route": "/preview"}]},
                {"rank": 2, "title": "Reports file read", "reason": "Caller supplies the report name used in a path join.", "evidence": [{"file": "app.py", "line": 12, "function": "reports", "route": "/reports"}]},
                {"rank": 3, "title": "Admin export", "reason": "Privilege boundary depends on a caller-supplied role header.", "evidence": [{"file": "app.py", "line": 16, "function": "admin_export", "route": "/admin/export"}]},
            ],
            "attack_surfaces": ["Outbound network request", "Filesystem read", "Caller-supplied role header"],
            "risk_paths": [
                {"label": "Preview URL path", "steps": ["GET /preview", "url parameter", "requests.get"], "evidence": [{"file": "app.py", "line": 10, "function": "preview", "route": "/preview"}]},
                {"label": "Report path read", "steps": ["GET /reports", "name parameter", "Path read"], "evidence": [{"file": "app.py", "line": 14, "function": "reports", "route": "/reports"}]},
                {"label": "Header role boundary", "steps": ["GET /admin/export", "x-role header", "export response"], "evidence": [{"file": "app.py", "line": 17, "function": "admin_export", "route": "/admin/export"}]},
            ],
            "adversarial_observations": [
                {"title": "Caller-controlled outbound URL", "risk": "high", "reason": "The preview route passes url into requests.get.", "evidence": [{"file": "app.py", "line": 10, "function": "preview", "route": "/preview"}], "potential_impact": "Outbound requests can cross trust boundaries.", "hardening_action": "Use allowlisted destinations and tight request controls."},
                {"title": "Caller-influenced filesystem path", "risk": "high", "reason": "The reports route combines REPORT_DIR with name before reading.", "evidence": [{"file": "app.py", "line": 14, "function": "reports", "route": "/reports"}], "potential_impact": "Unexpected files may become reachable if containment is missing.", "hardening_action": "Resolve and enforce directory containment."},
                {"title": "Header-only privileged boundary", "risk": "high", "reason": "Admin export trusts x-role from the request.", "evidence": [{"file": "app.py", "line": 17, "function": "admin_export", "route": "/admin/export"}], "potential_impact": "Privilege decisions are caller-controlled.", "hardening_action": "Use server-authenticated identity and authorization."},
            ],
            "hacker_hypotheses": [],
            "hardening_priorities": ["Add URL allowlisting.", "Enforce filesystem containment.", "Replace caller-supplied role header with real auth."],
        }
    return {
        "summary": "The audit fixture has limited attacker material compared with the adversarial fixture.",
        "attack_surface_score": 3.0,
        "score_reasoning": "A single report endpoint is visible, with validation but operational risks.",
        "top_targets": [{"rank": 1, "title": "Report generation", "reason": "It touches network/cache/file I/O.", "evidence": [{"file": "app.py", "line": 16, "function": "report", "route": "/report"}]}],
        "attack_surfaces": ["Report generation"],
        "risk_paths": [],
        "adversarial_observations": [],
        "hacker_hypotheses": [{"title": "Operational failure could affect availability", "risk": "medium", "reason": "Network and file I/O occur in the request flow.", "evidence": [{"file": "app.py", "line": 21, "function": "report", "route": "/report"}], "potential_impact": "Availability risk, not a confirmed exploit.", "hardening_action": "Move blocking work out of request path."}],
        "hardening_priorities": ["Keep reviewing blocking I/O in request paths."],
    }


def _brutal_payload(kind: str) -> dict:
    if kind == "brutal":
        return {
            "summary": "This repository has useful validation and helper separation, but it is not production-ready because request handling mixes async endpoints with blocking network and file I/O plus weak failure semantics.",
            "category_scores": {"security": 7, "architecture": 6, "reliability": 4, "maintainability": 6, "code_quality": 6.5, "production_readiness": 4},
            "category_analysis": [
                {"category": "security", "score": 7, "reasoning": "Pydantic model and positive user_id validation reduce direct input risk.", "evidence": [{"file": "app.py", "line": 8, "function": "", "route": ""}]},
                {"category": "reliability", "score": 4, "reasoning": "Blocking requests.get without timeout runs under an async request path.", "evidence": [{"file": "app.py", "line": 12, "function": "fetch_profile", "route": ""}]},
                {"category": "architecture", "score": 6, "reasoning": "A helper function separates the profile fetch, but request handling still owns cache and file side effects.", "evidence": [{"file": "app.py", "line": 11, "function": "fetch_profile", "route": ""}]},
                {"category": "maintainability", "score": 6, "reasoning": "Small code size and helper separation help, but broad exception handling hides failure modes.", "evidence": [{"file": "app.py", "line": 25, "function": "report", "route": "/report"}]},
                {"category": "code_quality", "score": 6.5, "reasoning": "Input validation is readable, but cache semantics are implicit.", "evidence": [{"file": "app.py", "line": 18, "function": "report", "route": "/report"}]},
                {"category": "production_readiness", "score": 4, "reasoning": "No timeout, process-local cache, synchronous file I/O, and swallowed exceptions are deployment risks.", "evidence": [{"file": "app.py", "line": 21, "function": "report", "route": "/report"}]},
            ],
            "code_review_rejections": [
                {"title": "Blocking network call inside async request flow", "severity": "high", "category": "reliability", "reason": "report() is async and calls fetch_profile(), which uses synchronous requests.get.", "evidence": [{"file": "app.py", "line": 12, "function": "fetch_profile", "route": ""}, {"file": "app.py", "line": 20, "function": "report", "route": "/report"}], "impact": "One slow upstream can tie up request handling.", "improvement": "Use an async HTTP client or move work to a worker."},
                {"title": "Outbound request has no timeout", "severity": "high", "category": "reliability", "reason": "requests.get is called without timeout.", "evidence": [{"file": "app.py", "line": 12, "function": "fetch_profile", "route": ""}], "impact": "Requests can hang indefinitely.", "improvement": "Set explicit connect/read timeouts."},
                {"title": "Process-local unbounded mutable cache", "severity": "medium", "category": "production_readiness", "reason": "CACHE grows by user_id with no bound or eviction.", "evidence": [{"file": "app.py", "line": 6, "function": "", "route": ""}, {"file": "app.py", "line": 21, "function": "report", "route": "/report"}], "impact": "Memory and multi-process consistency risks.", "improvement": "Use a bounded cache or external cache with TTL."},
                {"title": "Broad exception swallowing", "severity": "medium", "category": "reliability", "reason": "except Exception returns a generic error without logging.", "evidence": [{"file": "app.py", "line": 25, "function": "report", "route": "/report"}], "impact": "Failures lose observability.", "improvement": "Catch specific errors and log structured context."},
            ],
            "strongest_areas": ["Uses a Pydantic input model.", "Checks user_id > 0.", "Keeps HTTP fetch in a helper.", "Calls raise_for_status()."],
            "weakest_areas": [],
            "production_blockers": ["Blocking I/O and weak failure handling remain in the request path."],
            "top_improvements": ["Add timeout or async client.", "Bound the cache.", "Replace broad exception swallowing with logged, typed errors."],
        }
    if kind == "normal":
        scores = {"security": 3.5, "architecture": 5, "reliability": 5, "maintainability": 5, "code_quality": 5, "production_readiness": 3.5}
    else:
        scores = {"security": 4, "architecture": 5, "reliability": 4.5, "maintainability": 5, "code_quality": 5, "production_readiness": 4}
    return {
        "summary": "This repository has evidence-backed production risks and should not be treated as ready without hardening.",
        "category_scores": scores,
        "category_analysis": [{"category": category, "score": score, "reasoning": "Evidence-backed category assessment.", "evidence": [{"file": "app.py", "line": 1, "function": "", "route": ""}]} for category, score in scores.items()],
        "code_review_rejections": [{"title": "Security and production readiness need work", "severity": "high", "category": "security", "reason": "The repository shows risky request handling.", "evidence": [{"file": "app.py", "line": 1, "function": "", "route": ""}], "impact": "Deployment risk.", "improvement": "Harden the request boundary."}],
        "strongest_areas": [],
        "weakest_areas": [],
        "production_blockers": ["Production hardening is incomplete."],
        "top_improvements": ["Harden request boundaries.", "Add reliability controls.", "Improve observability."],
    }


def _detect_kind(prompt: str) -> str:
    if "/preview" in prompt and "/admin/export" in prompt:
        return "hacker"
    if "raise_for_status" in prompt and "CACHE" in prompt:
        return "brutal"
    return "normal"


async def _upload_and_analyze(kind: str, store: FakeProjectStore):
    spec = FIXTURES[kind]
    upload = UploadFile(filename=spec["filename"], file=io.BytesIO(_zip_bytes(spec["files"])))
    upload_result = await projects_router.upload_project(upload, session_id=f"session-{kind}", current_user=USER)
    project_id = upload_result["project_id"]

    analyze_response = await projects_router.analyze_project_by_id(project_id, current_user=USER)
    assert analyze_response.status_code == 202
    job_payload = json.loads(analyze_response.body)
    job = await projects_router.get_analysis_job(job_payload["job_id"], current_user=USER)
    assert job["status"] == "completed"
    project = await projects_router.get_project_by_id(project_id, current_user=USER)
    return project_id, project


def _assert_evidence_exists(report, project: dict):
    files = {entry["path"]: entry["content"] for entry in project.get("files", [])}
    for collection_name in ("top_targets", "risk_paths", "adversarial_observations", "hacker_hypotheses", "code_review_rejections", "category_analysis"):
        for item in getattr(report, collection_name, []) or []:
            for evidence in getattr(item, "evidence", []) or []:
                if evidence.file:
                    assert evidence.file in files
                    if evidence.line is not None:
                        assert 1 <= evidence.line <= len(files[evidence.file].splitlines())


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["normal", "hacker", "brutal"])
async def test_three_features_reuse_one_uploaded_project_and_keep_modes_distinct(feature_store, monkeypatch, kind):
    rag_calls = {"count": 0}

    async def unexpected_rag(*args, **kwargs):
        rag_calls["count"] += 1
        raise AssertionError("Hacker Mode and Brutal Audit must not call RAG")

    monkeypatch.setattr(projects_router, "retrieve_knowledge", unexpected_rag)

    async def fake_hacker_groq(messages, temperature=0.0):
        assert len(messages) == 1
        return json.dumps(_hacker_payload(_detect_kind(messages[0]["content"])))

    async def fake_brutal_groq(messages, temperature=0.0):
        assert len(messages) == 1
        return json.dumps(_brutal_payload(_detect_kind(messages[0]["content"])))

    monkeypatch.setattr(hacker_lens, "call_groq", fake_hacker_groq)
    monkeypatch.setattr(brutal_audit, "call_groq", fake_brutal_groq)

    before_project_count = feature_store._project_counter
    project_id, project = await _upload_and_analyze(kind, feature_store)

    hacker_report = await projects_router.hacker_lens_report(project_id, current_user=USER)
    brutal_report = await projects_router.brutal_audit_report(project_id, current_user=USER)

    assert isinstance(hacker_report, HackerLensReport)
    assert isinstance(brutal_report, BrutalAuditReport)
    assert feature_store._project_counter == before_project_count + 1
    assert project_id in feature_store.projects
    assert rag_calls["count"] == 0
    _assert_evidence_exists(hacker_report, project)
    _assert_evidence_exists(brutal_report, project)

    rules = {finding.get("rule_id") for finding in project.get("findings", [])}
    if kind == "normal":
        assert {"SEC-SQL-INJECTION", "SEC-HARDCODED-SECRET"}.issubset(rules)
        assert any("/user" in (target.reason + target.title) or any(e.route == "/user" for e in target.evidence) for target in hacker_report.top_targets)
        assert brutal_report.category_scores["security"] <= 4
    elif kind == "hacker":
        assert any(e.route == "/preview" for target in hacker_report.top_targets for e in target.evidence)
        assert any(e.route == "/reports" for target in hacker_report.top_targets for e in target.evidence)
        assert any(e.route == "/admin/export" for target in hacker_report.top_targets for e in target.evidence)
        assert "Outbound network request" in hacker_report.attack_surfaces
        assert len(hacker_report.risk_paths) >= 3
    else:
        assert len(project.get("findings", [])) <= 1
        assert sum(1 for item in hacker_report.adversarial_observations if item.risk in ("high", "critical")) == 0
        joined_rejections = " ".join(item.title + " " + item.reason for item in brutal_report.code_review_rejections)
        for expected in ("Blocking network call", "no timeout", "unbounded mutable cache", "Broad exception"):
            assert expected.lower() in joined_rejections.lower()
        strongest = " ".join(brutal_report.strongest_areas).lower()
        for expected in ("pydantic", "user_id > 0", "helper", "raise_for_status"):
            assert expected.lower() in strongest


@pytest.mark.asyncio
@pytest.mark.parametrize("service_module,runner", [(hacker_lens, hacker_lens.run_hacker_lens), (brutal_audit, brutal_audit.run_brutal_audit)])
async def test_new_feature_groq_malformed_json_retries_then_succeeds(monkeypatch, service_module, runner):
    calls = {"count": 0}

    async def fake_call_groq(messages, temperature=0.0):
        calls["count"] += 1
        if calls["count"] == 1:
            return "not json"
        if service_module is hacker_lens:
            return json.dumps(_hacker_payload("normal"))
        return json.dumps(_brutal_payload("normal"))

    monkeypatch.setattr(service_module, "call_groq", fake_call_groq)
    report = await runner({"files": [{"path": "app.py", "language": "python", "content": FIXTURES["normal"]["files"]["app.py"]}]})

    assert calls["count"] == 2
    assert report.error == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("service_module,runner", [(hacker_lens, hacker_lens.run_hacker_lens), (brutal_audit, brutal_audit.run_brutal_audit)])
@pytest.mark.parametrize("failure", ["provider failure", "timeout"])
async def test_new_feature_groq_provider_failure_is_controlled(monkeypatch, service_module, runner, failure):
    async def fake_call_groq(messages, temperature=0.0):
        raise GroqUnavailableError(failure)

    monkeypatch.setattr(service_module, "call_groq", fake_call_groq)
    report = await runner({"files": [{"path": "app.py", "language": "python", "content": FIXTURES["normal"]["files"]["app.py"]}]})

    assert report.error == failure
    assert "unavailable" in report.summary.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("service_module,runner", [(hacker_lens, hacker_lens.run_hacker_lens), (brutal_audit, brutal_audit.run_brutal_audit)])
async def test_new_feature_empty_model_response_is_error_not_fake_report(monkeypatch, service_module, runner):
    async def fake_call_groq(messages, temperature=0.0):
        return ""

    monkeypatch.setattr(service_module, "call_groq", fake_call_groq)
    report = await runner({"files": [{"path": "app.py", "language": "python", "content": FIXTURES["normal"]["files"]["app.py"]}]})

    assert report.error == "invalid_model_output"
    assert not getattr(report, "code_review_rejections", [])
    assert not getattr(report, "top_targets", [])
