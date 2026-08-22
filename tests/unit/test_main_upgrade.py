import pytest

from services.analyzer import analyze_project
from services.analyzers.rules import run_rules
from services.project_review import _chunk_content, _dedupe_against_deterministic, run_ai_quality_review
from services.structural import analyze_python_source, enclosing_symbol_for_line, line_range


def test_python_ast_extraction_returns_function_ranges_and_calls():
    source = """
import requests

async def handler(user_url):
    response = requests.get(user_url)
    return response.text
""".strip()
    module = analyze_python_source(source)
    assert module.parse_error is None
    assert module.imports == ["requests"]
    assert module.functions[0].name == "handler"
    assert module.functions[0].is_async is True
    assert module.functions[0].start_line == 3
    assert module.functions[0].end_line == 5
    assert module.functions[0].calls[0].name == "requests.get"
    assert line_range(source, 3, 5).startswith("async def handler")
    assert enclosing_symbol_for_line(module, 4).name == "handler"


def test_python_ast_failure_degrades_safely():
    module = analyze_python_source("def broken(:\n    pass")
    assert module.parse_error
    project = {"files": [{"path": "broken.py", "language": "python", "content": "def broken(:\n    pass"}]}
    analyzed = analyze_project(project)
    assert "findings" in analyzed
    assert analyzed["structuralMetadata"] == []


def test_structural_python_chunk_respects_function_boundaries():
    source = "\n\n".join(
        [
            "def first():\n    return 1",
            "def second(value):\n    risky = eval(value)\n    return risky",
        ]
    )
    chunks = _chunk_content(source, "app.py", "python")
    assert len(chunks) == 2
    assert "# SYMBOL: function first" in chunks[0]
    assert "def second" not in chunks[0]
    assert "# SYMBOL: function second" in chunks[1]


def test_large_file_deterministic_scan_reaches_end_of_file():
    source = "\n".join(["safe = 1"] * 12000 + ["API_KEY = 'super-secret-value'"])
    findings = run_rules("huge.py", "python", source)
    assert any(f["rule"] == "hardcoded_secret" and f["line"] == 12001 for f in findings)


def test_semantic_duplicate_deterministic_and_ai_is_merged():
    deterministic = {
        "file": "app.py",
        "line": 5,
        "rule": "subprocess_shell_true",
        "severity": "high",
        "category": "security",
        "message": "Shell/subprocess call with an unsanitized command string risks command injection",
        "evidence": "subprocess.run(cmd, shell=True)",
        "source": "deterministic",
    }
    ai = {
        **deterministic,
        "rule": "ai_quality_security",
        "message": "Potential command injection through shell=True",
        "source": "ai_quality",
    }
    assert _dedupe_against_deterministic([ai], {"app.py": [deterministic]}) == []
    assert deterministic["source"] == "ai_quality+deterministic"


def test_ai_privacy_duplicate_on_same_logging_line_is_not_appended():
    source = "\n".join(
        [
            "import logging",
            "logger = logging.getLogger(__name__)",
            "def authenticate(token: str):",
            "    logger.info('auth attempt token=%s', token)",
            "    return token.startswith('session-')",
        ]
    )
    deterministic = [
        finding for finding in run_rules("app.py", "python", source)
        if finding["rule"] == "sensitive_logging"
    ]
    assert len(deterministic) == 1
    assert deterministic[0]["line"] == 4

    ai_duplicate = {
        "file": "app.py",
        "line": 4,
        "rule": "ai_quality_privacy",
        "severity": "low",
        "category": "privacy",
        "message": "Sensitive authentication token is logged in plaintext, risking credential leakage.",
        "evidence": "logger.info('auth attempt token=%s', token)",
        "source": "ai_quality",
    }

    kept = _dedupe_against_deterministic(
        [ai_duplicate],
        {"app.py": deterministic},
        {"app.py": source},
    )
    assert kept == []
    assert deterministic[0]["source"] == "ai_quality+deterministic"


def test_ai_weak_crypto_duplicate_on_nearby_password_hash_line_is_not_appended():
    source = "\n".join(
        [
            "import hashlib",
            "def hash_password(password: str) -> str: return hashlib.md5(password.encode()).hexdigest()",
            "def verify(password: str, stored: str) -> bool: return hash_password(password) == stored",
        ]
    )
    deterministic = [
        finding for finding in run_rules("app.py", "python", source)
        if finding["rule"] == "weak_crypto_hash"
    ]
    assert len(deterministic) == 1
    assert deterministic[0]["line"] == 2

    ai_duplicate = {
        "file": "app.py",
        "line": 3,
        "rule": "ai_quality_security",
        "severity": "critical",
        "category": "security",
        "message": "Insecure password hashing using MD5, which is fast and vulnerable to brute-force attacks.",
        "evidence": "hash_password(password)",
        "source": "ai_quality",
    }

    kept = _dedupe_against_deterministic(
        [ai_duplicate],
        {"app.py": deterministic},
        {"app.py": source},
    )
    assert kept == []
    assert deterministic[0]["source"] == "ai_quality+deterministic"


def test_sensitive_logging_finding_has_logging_specific_remediation():
    findings = run_rules(
        "app.py",
        "python",
        "import logging\nlogger=logging.getLogger(__name__)\nlogger.info('token=%s', token)\n",
    )
    logging_finding = next(finding for finding in findings if finding["rule"] == "sensitive_logging")
    assert "Do not log token" in logging_finding["fix_suggestion"]


def test_nearby_different_findings_are_not_merged():
    deterministic = {
        "file": "app.py",
        "line": 5,
        "rule": "dangerous_eval",
        "severity": "critical",
        "category": "security",
        "message": "eval",
        "evidence": "eval(payload)",
    }
    ai = {
        "file": "app.py",
        "line": 6,
        "rule": "ai_quality_security",
        "severity": "high",
        "category": "security",
        "message": "Outbound request has no timeout",
        "evidence": "requests.get(url)",
        "source": "ai_quality",
    }
    assert _dedupe_against_deterministic([ai], {"app.py": [deterministic]}) == [ai]


@pytest.mark.asyncio
async def test_partial_semantic_analysis_records_partial_coverage(monkeypatch):
    async def fake_review_chunk(path, language, chunk, semaphore):
        return [], True

    monkeypatch.setattr("services.project_review._review_chunk", fake_review_chunk)
    project = {
        "files": [
            {"path": f"f{i}.py", "language": "python", "content": f"def f{i}():\n    return {i}"}
            for i in range(45)
        ],
        "findings": [],
    }
    coverage = await run_ai_quality_review(project)
    assert coverage["semantic_coverage"] == "partial"
    assert coverage["eligible_files"] == 45
    assert coverage["ai_reviewed_files"] == 40
    assert coverage["ai_finding_count"] == 0
    assert project["findings"] == []
    assert coverage["files_skipped"] == 5
    assert coverage["partial_reasons"]
