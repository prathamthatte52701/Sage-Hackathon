"""Regression contracts for the current paste-fix workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "client" / "src"
APP = (ROOT / "App.jsx").read_text()
API = (ROOT / "api" / "client.js").read_text()


def _body(name: str) -> str:
    start = APP.index(f"const {name} = async")
    brace = APP.index("{", start)
    depth = 0
    for index in range(brace, len(APP)):
        if APP[index] == "{":
            depth += 1
        elif APP[index] == "}":
            depth -= 1
            if depth == 0:
                return APP[brace + 1:index]
    raise AssertionError(f"Could not extract {name}")


def test_paste_fix_generation_uses_preview_api_without_mutating_snippet_source():
    body = _body("handleGenerateFix")
    assert "transformFinding(" in body
    assert "setSnippetCode(" not in body


def test_project_apply_is_followed_by_canonical_reanalysis_of_stored_source():
    body = _body("handleApplyFix")
    assert "await applyProjectFix(" in body
    assert "await reanalyzeProject(projectBundle.project_id)" in body
    assert body.index("await applyProjectFix(") < body.index("await reanalyzeProject(projectBundle.project_id)")


def test_project_fix_request_uses_stable_finding_identity_when_available():
    assert "return { finding_id: finding.finding_id };" in API
    assert "finding_index: -1" not in API
    assert "applyProjectFix(projectId, finding)" in API
    assert "transformFinding(projectId, finding)" in API


def test_generated_fix_modal_does_not_invent_a_passing_validation_state():
    modal = (ROOT / "components" / "FixValidationModal.jsx").read_text()
    assert "target_found: true" not in modal
    assert "Boolean(fixData.can_apply)" in modal
    assert "disabled={applying || !allPass}" in modal


def test_analysis_client_waits_for_job_before_loading_results():
    assert "waitForAnalysisJob" in API
    assert "await waitForAnalysisJob(data.job_id)" in API
    assert "return await getProject(projectId)" in API


def test_preview_api_does_not_apply_project_fixes():
    transform = API[API.index("export async function transformFinding"):API.index("export async function reasonFinding")]
    assert "/findings/transform" in transform
    assert "/fixes/apply" not in transform
