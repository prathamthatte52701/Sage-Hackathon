"""Phase 3.7 certification: SEC-UNSAFE-DESERIALIZATION."""

from services.analyzers.rules import run_rules
from services.security_rules import to_closed_world_findings


def _deserialization_findings(code: str) -> list[dict]:
    findings = to_closed_world_findings(run_rules("repository/app.py", "python", code))
    return [finding for finding in findings if finding["rule_id"] == "SEC-UNSAFE-DESERIALIZATION"]


def test_pickle_loads_is_reported_with_canonical_evidence():
    findings = _deserialization_findings("pickle.loads(request.get_data())")

    assert len(findings) == 1
    assert findings[0]["cwe"] == "CWE-502"
    assert findings[0]["deterministic_evidence"] is True


def test_pickle_load_and_aliases_are_reported():
    alias = "import pickle as serializer\nserializer.load(upload.stream)"
    direct_import = "from pickle import loads as decode\ndecode(blob)"

    assert len(_deserialization_findings(alias)) == 1
    assert len(_deserialization_findings(direct_import)) == 1


def test_yaml_load_without_loader_is_reported():
    assert len(_deserialization_findings("yaml.load(request.data)")) == 1


def test_yaml_unsafe_loader_is_reported():
    assert len(_deserialization_findings("yaml.load(raw_text, Loader=yaml.Loader)")) == 1


def test_yaml_unsafe_load_alias_is_reported():
    code = "from yaml import unsafe_load as decode\ndecode(raw_text)"

    assert len(_deserialization_findings(code)) == 1


def test_yaml_safe_loader_is_not_reported():
    assert _deserialization_findings("yaml.load(raw_text, Loader=yaml.SafeLoader)") == []


def test_imported_safe_loader_is_not_reported():
    code = "from yaml import SafeLoader\nyaml.load(raw_text, Loader=SafeLoader)"

    assert _deserialization_findings(code) == []


def test_imported_load_alias_with_safe_loader_is_not_reported():
    code = "from yaml import load as parse, SafeLoader\nparse(raw_text, Loader=SafeLoader)"

    assert _deserialization_findings(code) == []


def test_yaml_safe_load_and_json_loads_are_not_reported():
    code = "yaml.safe_load(raw_text)\njson.loads(raw_text)"

    assert _deserialization_findings(code) == []


def test_imports_comments_and_strings_are_not_reported():
    code = "import pickle\n# pickle.loads(blob)\nexample = \"yaml.load(raw)\""

    assert _deserialization_findings(code) == []


def test_repeated_analysis_is_deterministic():
    code = "pickle.loads(blob)"
    runs = [_deserialization_findings(code) for _ in range(10)]

    assert all(run == runs[0] for run in runs)
    assert runs[0][0]["line"] == 1
