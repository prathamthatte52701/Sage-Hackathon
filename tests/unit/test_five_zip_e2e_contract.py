import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi import UploadFile

import routers.projects as projects_router
from services.security_rules import SUPPORTED_SECURITY_RULES


USER = {"_id": "demo-user", "email": "demo@example.com"}
SUITE_ROOT = Path(r"C:\Users\Pratham\Downloads\SAGE_PYTHON_50_BENCHMARK_SUITE\sage_python_50_suite")
ZIP_DIR = SUITE_ROOT / "inner_zips"
FIRST_FIVE = [
    "py_001_hardcoded_secret.zip",
    "py_002_eval_untrusted_input.zip",
    "py_003_sql_injection.zip",
    "py_004_shell_injection.zip",
    "py_005_path_traversal.zip",
]
EXPECTED_RULES = {
    "py_001_hardcoded_secret.zip": {"SEC-HARDCODED-SECRET"},
    "py_002_eval_untrusted_input.zip": {"SEC-EVAL-EXEC"},
    "py_003_sql_injection.zip": {"SEC-SQL-INJECTION"},
    "py_004_shell_injection.zip": {"SEC-COMMAND-INJECTION"},
    "py_005_path_traversal.zip": {"SEC-PATH-TRAVERSAL-FILE"},
}


class FakeProjectStore:
    def __init__(self):
        self.projects: dict[str, dict] = {}
        self.binary_blobs: dict[str, bytes] = {}
        self.jobs: dict[str, dict] = {}
        self._project_counter = 0
        self._binary_counter = 0
        self._job_counter = 0

    def _persist_file_refs(self, project: dict) -> None:
        for file_entry in project.get("files", []):
            binary = file_entry.pop("binary_content", None)
            if binary is not None:
                self._binary_counter += 1
                ref = f"binary-{self._binary_counter}"
                self.binary_blobs[ref] = binary
                file_entry["binary_ref"] = ref

    async def save_project(self, project: dict, session_id: str, owner_user_id: str) -> str:
        self._project_counter += 1
        project_id = f"e2e-project-{self._project_counter}"
        doc = copy.deepcopy(project)
        self._persist_file_refs(doc)
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

    async def update_owned_project(
        self,
        project_id: str,
        owner_user_id: str,
        updates: dict,
        *,
        expected_source_revision: int | None = None,
    ) -> bool:
        doc = self.projects.get(project_id)
        if doc is None or doc.get("owner_user_id") != owner_user_id:
            return False
        if expected_source_revision is not None and int(doc.get("source_revision", 0)) != expected_source_revision:
            return False
        updates = copy.deepcopy(updates)
        if "files" in updates:
            self._persist_file_refs(updates)
        doc.update(updates)
        return True

    async def update_owned_finding(self, project_id: str, owner_user_id: str, finding_id: str, updates: dict) -> bool:
        doc = self.projects.get(project_id)
        if doc is None or doc.get("owner_user_id") != owner_user_id:
            return False
        for finding in doc.get("findings", []):
            if finding.get("finding_id") == finding_id:
                finding.update(copy.deepcopy(updates))
                return True
        return False

    async def fetch_binary_content(self, ref: str) -> bytes:
        return self.binary_blobs[ref]

    async def enqueue_analysis(self, project_id: str, owner_user_id: str, work):
        self._job_counter += 1
        job_id = f"e2e-job-{self._job_counter}"
        self.jobs[job_id] = {"_id": job_id, "project_id": project_id, "owner_user_id": owner_user_id, "status": "running"}
        result = await work(job_id)
        status = "partial" if result.get("partial") else "completed"
        self.jobs[job_id].update({"status": status, "result": result})
        return copy.deepcopy(self.jobs[job_id]), True

    async def get_owned_analysis_job(self, job_id: str, owner_user_id: str):
        job = self.jobs.get(job_id)
        if job is None or job.get("owner_user_id") != owner_user_id:
            return None
        return copy.deepcopy(job)


@pytest.fixture
def e2e_store(monkeypatch):
    store = FakeProjectStore()
    monkeypatch.setattr(projects_router, "save_project", store.save_project)
    monkeypatch.setattr(projects_router, "get_owned_project", store.get_owned_project)
    monkeypatch.setattr(projects_router, "get_owned_project_metadata", store.get_owned_project_metadata)
    monkeypatch.setattr(projects_router, "get_owned_project_file", store.get_owned_project_file)
    monkeypatch.setattr(projects_router, "update_owned_project", store.update_owned_project)
    monkeypatch.setattr(projects_router, "update_owned_finding", store.update_owned_finding)
    monkeypatch.setattr(projects_router, "fetch_binary_content", store.fetch_binary_content)
    monkeypatch.setattr(projects_router, "enqueue_analysis", store.enqueue_analysis)
    monkeypatch.setattr(projects_router, "get_analysis_job_with_recovery", store.get_owned_analysis_job)

    async def no_ai_finding_creation(project: dict) -> dict:
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

    monkeypatch.setattr(projects_router, "run_ai_quality_review", no_ai_finding_creation)
    return store


def _zip_manifest(zip_bytes: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return {
            info.filename.replace("\\", "/"): hashlib.sha256(zf.read(info.filename)).hexdigest()
            for info in zf.infolist()
            if not info.is_dir()
        }


async def _streaming_response_bytes(response) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _finding_signature(project: dict) -> list[tuple]:
    return sorted(
        (
            finding.get("finding_id"),
            finding.get("rule_id"),
            finding.get("file"),
            finding.get("line"),
            finding.get("severity"),
            finding.get("evidence"),
        )
        for finding in project.get("findings", [])
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("zip_name", FIRST_FIVE)
async def test_first_five_supplied_zips_pass_upload_analyze_source_and_download_integrity(e2e_store, zip_name):
    zip_path = ZIP_DIR / zip_name
    assert zip_path.is_file(), f"missing supplied fixture {zip_path}"
    zip_bytes = zip_path.read_bytes()
    original_manifest = _zip_manifest(zip_bytes)

    upload = UploadFile(filename=zip_name, file=io.BytesIO(zip_bytes))
    upload_result = await projects_router.upload_project(
        file=upload,
        session_id="e2e-session",
        current_user=USER,
    )
    project_id = upload_result["project_id"]

    signatures = []
    for _ in range(3):
        analyze_response = await projects_router.analyze_project_by_id(project_id, current_user=USER)
        assert analyze_response.status_code == 202
        job_payload = json.loads(analyze_response.body)
        job = await projects_router.get_analysis_job(job_payload["job_id"], current_user=USER)
        assert job["status"] == "completed"

        project = await projects_router.get_project_by_id(project_id, current_user=USER)
        signatures.append(_finding_signature(project))

        assert project["analysis_status"] == "completed"
        assert project["ai_review_coverage"]["ai_finding_count"] == 0
        assert all(finding.get("rule_id") in SUPPORTED_SECURITY_RULES for finding in project["findings"])
        assert {finding["rule_id"] for finding in project["findings"]} == EXPECTED_RULES[zip_name]
        assert len(project["findings"]) == len({finding["finding_id"] for finding in project["findings"]})

        for finding in project["findings"]:
            source = await projects_router.get_project_file(project_id, finding["file"], current_user=USER)
            assert source["content"]
            assert finding["evidence"] in source["content"]

    assert signatures[0] == signatures[1] == signatures[2]

    download_response = await projects_router.download_fixed_project(project_id, current_user=USER)
    assert download_response.status_code == 200
    downloaded = await _streaming_response_bytes(download_response)
    downloaded_manifest = _zip_manifest(downloaded)
    assert downloaded_manifest == original_manifest


FIX_SPECS = {
    "py_001_hardcoded_secret.zip": {
        "rule": "SEC-HARDCODED-SECRET",
        "original_snippet": 'API_KEY = "demo-secret-key-123"',
        "proposed_fix": 'API_KEY = os.environ["API_KEY"]',
    },
    "py_002_eval_untrusted_input.zip": {
        "rule": "SEC-EVAL-EXEC",
        "original_snippet": "    return eval(expression)",
        "proposed_fix": "    return ast.literal_eval(expression)",
    },
    "py_003_sql_injection.zip": {
        "rule": "SEC-SQL-INJECTION",
        "original_snippet": '    query = f"SELECT id, name FROM users WHERE name = \'{name}\'"\n    return conn.execute(query).fetchall()',
        "proposed_fix": '    query = "SELECT id, name FROM users WHERE name = ?"\n    return conn.execute(query, (name,)).fetchall()',
    },
    "py_004_shell_injection.zip": {
        "rule": "SEC-COMMAND-INJECTION",
        "original_snippet": '    command = f"ping -c 1 {host}"\n    return subprocess.run(command, shell=True, capture_output=True, text=True).stdout',
        "proposed_fix": '    command = ["ping", "-c", "1", host]\n    return subprocess.run(command, shell=False, capture_output=True, text=True).stdout',
    },
    "py_005_path_traversal.zip": {
        "rule": "SEC-PATH-TRAVERSAL-FILE",
        "original_snippet": "    return (UPLOAD_ROOT / filename).read_text(encoding='utf-8')",
        "proposed_fix": (
            "    target = (UPLOAD_ROOT / filename).resolve()\n"
            "    if not target.is_relative_to(UPLOAD_ROOT.resolve()):\n"
            "        raise ValueError('invalid path')\n"
            "    return target.read_text(encoding='utf-8')"
        ),
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("zip_name", FIRST_FIVE)
async def test_full_fix_apply_reanalyze_download_lifecycle(e2e_store, monkeypatch, zip_name):
    """The mandatory workflow the spec requires end-to-end, for every one of
    the 5 supplied ZIPs (regression law: every previously-passed ZIP is
    re-verified on every run, not just the newest one): upload -> analyze
    -> generate fix -> apply (exactly once) -> reanalyze (fresh, not
    reapplied) -> verify the original finding is gone -> download ->
    verify ONLY the fixed file changed, everything else byte-identical.

    generate_fix (the actual Groq call) is mocked to a deterministic patch --
    Groq's prose quality is covered elsewhere (grounding/prompt tests); this
    test is about the APPLY/REANALYZE/DOWNLOAD *mechanics* being correct,
    which must hold regardless of what the model returns.
    """
    from models.schemas import FindingTransform

    spec = FIX_SPECS[zip_name]
    zip_path = ZIP_DIR / zip_name
    zip_bytes = zip_path.read_bytes()
    original_manifest = _zip_manifest(zip_bytes)

    async def fake_generate_fix(finding, code_snippet, language, standards, related_files=None, knowledge=None):
        return FindingTransform(
            original_snippet=spec["original_snippet"],
            proposed_fix=spec["proposed_fix"],
            explanation="Deterministic test fix.",
            confidence=0.9,
        )

    monkeypatch.setattr(projects_router, "generate_fix", fake_generate_fix)

    upload = UploadFile(filename=zip_name, file=io.BytesIO(zip_bytes))
    upload_result = await projects_router.upload_project(file=upload, session_id="e2e-session", current_user=USER)
    project_id = upload_result["project_id"]

    analyze_response = await projects_router.analyze_project_by_id(project_id, current_user=USER)
    job_payload = json.loads(analyze_response.body)
    job = await projects_router.get_analysis_job(job_payload["job_id"], current_user=USER)
    assert job["status"] == "completed"

    before_project = await projects_router.get_project_by_id(project_id, current_user=USER)
    before_source_revision = before_project["source_revision"]
    target_finding = next(f for f in before_project["findings"] if f["rule_id"] == spec["rule"])
    finding_id = target_finding["finding_id"]

    # --- Generate: must NOT mutate source ---
    from models.schemas import FindingReasonRequest

    transform_result = await projects_router.transform_finding(
        project_id, FindingReasonRequest(finding_id=finding_id), current_user=USER
    )
    after_generate_project = await projects_router.get_project_by_id(project_id, current_user=USER)
    assert after_generate_project["source_revision"] == before_source_revision, "Generate must not mutate source"
    assert transform_result.can_apply is True, f"expected an applicable patch, got {transform_result.apply_failure_reason!r}"

    # --- Preview (re-fetch, no mutation) also must not change anything ---
    preview_project = await projects_router.get_project_by_id(project_id, current_user=USER)
    assert preview_project["source_revision"] == before_source_revision

    # --- Apply: exactly one mutation ---
    from models.schemas import ApplyProjectFixRequest

    apply_response = await projects_router.apply_project_fix(
        project_id, ApplyProjectFixRequest(finding_id=finding_id), current_user=USER
    )
    assert apply_response["status"] == "applied"

    applied_project = await projects_router.get_project_by_id(project_id, current_user=USER)
    assert applied_project["source_revision"] == before_source_revision + 1
    assert applied_project["analysis_status"] == "stale"
    app_py = next(f for f in applied_project["files"] if f["path"] == "app.py")
    assert spec["original_snippet"] not in app_py["content"]
    assert spec["proposed_fix"] in app_py["content"]

    # --- Duplicate Apply must be safely rejected, not double-applied ---
    second_apply = await projects_router.apply_project_fix(
        project_id, ApplyProjectFixRequest(finding_id=finding_id), current_user=USER
    )
    assert second_apply.status_code in (400, 409), "re-applying an already-applied fix must not silently succeed"
    unchanged_project = await projects_router.get_project_by_id(project_id, current_user=USER)
    assert unchanged_project["source_revision"] == before_source_revision + 1, "duplicate apply must not bump revision again"

    # --- Reanalyze: fresh from current (already-patched) source, not a reapply ---
    reanalyze_response = await projects_router.reanalyze_project(project_id, None, current_user=USER)
    assert reanalyze_response.status_code == 202
    reanalyze_job_payload = json.loads(reanalyze_response.body)
    reanalyze_job = await projects_router.get_analysis_job(reanalyze_job_payload["job_id"], current_user=USER)
    assert reanalyze_job["status"] == "completed"

    final_project = await projects_router.get_project_by_id(project_id, current_user=USER)
    assert final_project["analysis_status"] == "completed"
    final_findings_for_rule = [f for f in final_project["findings"] if f["rule_id"] == spec["rule"] and f["file"] == "app.py"]
    assert not final_findings_for_rule, (
        "the fixed pattern must no longer be detected -- static security re-scan "
        "no longer finds the previous pattern"
    )
    # No ghost accumulation: reanalysis must not have appended onto the stale set.
    assert len(final_project["findings"]) == len({f["finding_id"] for f in final_project["findings"]})

    # --- Download: only app.py may differ; everything else byte-identical ---
    download_response = await projects_router.download_fixed_project(project_id, current_user=USER)
    assert download_response.status_code == 200
    downloaded = await _streaming_response_bytes(download_response)
    downloaded_manifest = _zip_manifest(downloaded)

    assert set(downloaded_manifest.keys()) == set(original_manifest.keys()), "no file may appear or disappear"
    changed_files = {path for path in original_manifest if original_manifest[path] != downloaded_manifest[path]}
    assert changed_files == {"app.py"}, f"only app.py should differ, got {changed_files}"
