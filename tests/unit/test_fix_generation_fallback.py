"""Regression tests for deterministic recovery of invalid model patch previews."""

from models.schemas import FindingTransform
from routers import projects
from services.patching import apply_structured_patch


def _source() -> str:
    return (
        "import random,string\r\n"
        "\r\n"
        "def reset_token():\r\n"
        "    alphabet=string.ascii_letters+string.digits\r\n"
        "    return ''.join(random.choice(alphabet) for _ in range(32))\r\n"
    )


def test_invalid_model_preview_recovers_to_an_exact_random_choice_patch():
    model_preview = FindingTransform(
        original_snippet="import random,string\n\ndef reset_token():\n    return 'not the actual source'",
        proposed_fix="import random,string,secrets\n\ndef reset_token():\n    return 'also not the actual source'",
    )
    finding = {"file": "tokens.py", "line": 5, "rule": "insecure_random_secret"}

    result = projects._enrich_transform(model_preview, finding, _source())

    assert result.can_apply is True
    assert result.apply_failure_reason == ""
    assert result.original_code == _source()
    assert "import random,string, secrets" in result.fixed_code
    assert "secrets.choice(alphabet)" in result.fixed_code


def test_recovered_random_choice_patch_applies_with_source_hash_and_keeps_crlf():
    source = _source()
    result = projects._enrich_transform(
        FindingTransform(original_snippet="missing", proposed_fix="also missing"),
        {"file": "tokens.py", "line": 5, "rule": "insecure_random_secret"},
        source,
    )

    applied = apply_structured_patch(
        source,
        result.original_code,
        result.fixed_code,
        expected_hash=result.source_hash,
    )

    assert result.can_apply is True
    assert "random.choice(" not in applied.patched
    assert "secrets.choice(" in applied.patched
    assert "\n" not in applied.patched.replace("\r\n", "")
