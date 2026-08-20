from pathlib import Path


APP = Path(__file__).resolve().parents[2] / "client" / "src" / "App.jsx"


def _function_body(source: str, name: str) -> str:
    start = source.index(f"async function {name}")
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:index]
    raise AssertionError(f"Could not extract {name}")


def _component_source(source: str, component: str, next_function: str) -> str:
    start = source.index(f"function {component}")
    end = source.index(f"function {next_function}", start)
    return source[start:end]


def _function_body_in(source: str, name: str) -> str:
    start = source.index(f"async function {name}")
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:index]
    raise AssertionError(f"Could not extract {name}")


def test_generate_fix_does_not_mutate_source():
    source = APP.read_text()
    body = _function_body(source, "generateFix")

    assert "setCode(" not in body
    assert "generatePasteFix(code, language, issue)" in body
    assert "setFixes(" in body


def test_regenerate_fix_reuses_preview_path_without_source_mutation():
    source = APP.read_text()
    body = _function_body(source, "generateFix")

    assert "setCode(" not in body
    assert "setStates(" in body
    assert "Fix applied" not in body


def test_diff_preview_does_not_mutate_source():
    source = APP.read_text()
    start = source.index("function FixPanel")
    end = source.index("export default function App", start)
    body = source[start:end]

    assert "setCode(" not in body
    assert "Fix preview" in body
    assert "Proposed preview" in body


def test_valid_apply_fix_is_only_paste_path_that_mutates_source():
    source = APP.read_text()
    paste_body = _component_source(source, "PasteReviewResults", "ReviewSection")
    apply_body = _function_body_in(paste_body, "applyFix")

    assert paste_body.count("setCode(") == 1
    assert "setCode(updated)" in apply_body
    assert "setStates((items) => ({ ...items, [key]: \"Fix applied\" }))" in apply_body


def test_double_apply_is_disabled_after_fix_applied():
    source = APP.read_text()

    assert 'state === "Fix applied"' in source
    assert "applyValidatedReplacement(code, fix, appliedSpans)" in source


def test_generated_but_unapplied_patch_ignored_by_reanalysis():
    source = APP.read_text()
    body = _function_body(source, "reanalyzePaste")

    assert "reviewCode(code, language, sessionId)" in body
    assert "fixes" not in body
    assert "proposed_fix" not in body


def test_download_before_apply_does_not_export_preview_fix():
    source = APP.read_text()

    assert "const hasAppliedPatches = appliedSpans.length > 0" in source
    assert 'disabled={!hasAppliedPatches}' in source
    assert "downloadTextFile(`fixed-code.${languageExtension(language)}`, code)" in source


def test_multiple_findings_keep_independent_patch_state():
    source = APP.read_text()

    assert "fixes[`${issue.source}-${index}`]" in source
    assert "setFixes((items) => ({ ...items, [key]: fix }))" in source
    assert "states[`${issue.source}-${index}`]" in source
