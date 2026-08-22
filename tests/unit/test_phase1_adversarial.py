import json
import time

import pytest

from models.schemas import Issue
from services.analyzer import analyze_project
from services.analyzers.rules import run_rules
from services.grounding import ground_issue
from services.project_review import (
    CONCURRENCY_LIMIT,
    _chunk_content,
    _dedupe_against_deterministic,
    _issue_to_project_finding,
    _review_chunk,
    run_ai_quality_review,
)
from services.structural import analyze_python_source, enclosing_symbol_for_line


class TestASTStructure:
    def test_nested_functions_classes_imports_and_routes_are_represented(self):
        source = '''
import os as operating_system
from .services import users

@app.get("/users/{user_id}")
@app.post("/users")
async def route(user_id: str):
    import json
    def nested():
        return json.loads(user_id)
    return nested()

class Service(Base):
    class Inner:
        pass

    @staticmethod
    async def load():
        return await route("1")
'''.strip()
        module = analyze_python_source(source)
        assert module.parse_error is None
        assert "os" in module.imports
        assert "json" in module.imports
        assert ".services" in module.from_imports
        function_names = {fn.name for fn in module.functions}
        class_names = {cls.name for cls in module.classes}
        assert {"route", "nested", "load"} <= function_names
        assert {"Service", "Inner"} <= class_names
        route = next(fn for fn in module.functions if fn.name == "route")
        assert {r["method"] for r in route.routes} == {"GET", "POST"}
        assert enclosing_symbol_for_line(module, 9).name == "nested"

    def test_malformed_decorator_degrades_to_parse_error_not_crash(self):
        module = analyze_python_source("@app.get('/x')\ndef broken(:\n    pass")
        assert module.parse_error
        assert module.functions == []


class TestChunking:
    def test_module_level_code_before_between_and_after_functions_is_preserved(self):
        source = "\n".join(
            [
                "API_KEY = 'top-secret'",
                "",
                "def one():",
                "    return 1",
                "",
                "print('between')",
                "",
                "def two():",
                "    return 2",
                "",
                "requests.get(user_url)",
            ]
        )
        chunks = "\n---\n".join(_chunk_content(source, "app.py", "python"))
        assert "API_KEY = 'top-secret'" in chunks
        assert "print('between')" in chunks
        assert "requests.get(user_url)" in chunks
        assert "# LINES: 1-1" in chunks
        assert "# SYMBOL: function one" in chunks

    def test_huge_function_is_split_with_real_line_headers_and_tail_content(self):
        body = ["def big(user_url):"]
        body.extend("    x = 1" for _ in range(900))
        body.append("    return requests.get(user_url)")
        source = "\n".join(body)
        chunks = _chunk_content(source, "huge.py", "python")
        assert len(chunks) > 1
        assert any("requests.get(user_url)" in chunk for chunk in chunks)
        assert all("# LINES:" in chunk for chunk in chunks)

    def test_invalid_python_falls_back_to_line_chunking(self):
        source = "def broken(:\n" + "\n".join("x = 1" for _ in range(1000))
        chunks = _chunk_content(source, "broken.py", "python")
        assert chunks
        assert chunks[0].startswith("# FILE: broken.py")


class TestLargeFiles:
    def test_100k_line_tail_detection_and_line_number_accuracy(self):
        source = "\n".join(["safe = 1"] * 100000 + ["password = 'real-secret-value'"])
        start = time.perf_counter()
        findings = run_rules("large.py", "python", source)
        elapsed = time.perf_counter() - start
        assert any(f["rule"] == "hardcoded_secret" and f["line"] == 100001 for f in findings)
        assert elapsed < 5


class TestCoverage:
    @pytest.mark.asyncio
    async def test_failed_ai_chunk_is_counted_and_deterministic_findings_survive(self, monkeypatch):
        async def fake_review_chunk(path, language, chunk, semaphore):
            if "bad" in path:
                return [], False
            return [
                {
                    "file": path,
                    "line": 1,
                    "rule": "ai_quality_security",
                    "severity": "critical",
                    "category": "security",
                    "message": "critical",
                    "evidence": "eval(payload)",
                    "source": "ai_quality",
                }
            ], True

        monkeypatch.setattr("services.project_review._review_chunk", fake_review_chunk)
        project = {
            "files": [
                {"path": "good.py", "language": "python", "content": "eval(payload)"},
                {"path": "bad.py", "language": "python", "content": "eval(payload)"},
            ],
            "findings": [{"file": "good.py", "line": 1, "rule": "dangerous_eval", "severity": "critical", "category": "security", "evidence": "eval(payload)"}],
        }
        coverage = await run_ai_quality_review(project)
        assert coverage["ai_chunks_total"] == 2
        assert coverage["ai_chunks_completed"] == 1
        assert coverage["failed_ai_chunks"] == 1
        assert coverage["semantic_coverage"] == "partial"
        assert coverage["ai_candidate_count"] == 1
        assert coverage["ai_finding_count"] == 0
        assert any(f["rule"] == "dangerous_eval" for f in project["findings"])
        assert all(f.get("source") != "ai_quality" for f in project["findings"])

    @pytest.mark.asyncio
    async def test_zero_eligible_files_has_sensible_complete_zero_coverage(self):
        coverage = await run_ai_quality_review({"files": [{"path": "test_app.py", "language": "python", "content": "eval(x)"}], "findings": []})
        assert coverage["eligible_files"] == 0
        assert coverage["ai_chunks_total"] == 0
        assert coverage["semantic_coverage"] == "complete"


class TestDeduplication:
    def test_ai_critical_duplicate_upgrades_deterministic_medium_without_overwriting_evidence(self):
        deterministic = {
            "file": "app.py",
            "line": 10,
            "rule": "permissive_cors",
            "severity": "medium",
            "category": "security",
            "message": "Wildcard CORS",
            "evidence": "allow_origins=['*']",
            "source": "deterministic",
        }
        ai = {**deterministic, "rule": "ai_quality_security", "severity": "critical", "message": "CORS allows all origins", "source": "ai_quality"}
        assert _dedupe_against_deterministic([ai], {"app.py": [deterministic]}) == []
        assert deterministic["severity"] == "medium"
        assert deterministic["message"] == "Wildcard CORS"
        assert deterministic["evidence"] == "allow_origins=['*']"

    def test_two_legitimate_same_line_vulnerabilities_remain_distinct(self):
        deterministic = {"file": "app.py", "line": 1, "rule": "dangerous_eval", "severity": "critical", "category": "security", "message": "eval", "evidence": "eval(x)"}
        ai = {"file": "app.py", "line": 1, "rule": "ai_quality_security", "severity": "high", "category": "security", "message": "request has no timeout", "evidence": "requests.get(url)", "source": "ai_quality"}
        assert _dedupe_against_deterministic([ai], {"app.py": [deterministic]}) == [ai]


class TestSeverity:
    @pytest.mark.parametrize("severity", ["critical", "high", "medium", "low"])
    def test_ai_project_finding_preserves_valid_severity(self, severity):
        issue = Issue(line=1, severity=severity, category="security", issue="x", evidence="eval(x)", confidence=0.9)
        assert _issue_to_project_finding(issue, "app.py")["severity"] == severity


class TestMalformedAI:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw", ["hello", '{"issues":', json.dumps({"issues": [{"line": 999, "severity": 99, "confidence": "very high"}]})])
    async def test_invalid_or_wrong_typed_ai_output_gracefully_returns_no_findings(self, monkeypatch, raw):
        async def fake_call_groq(messages):
            return raw

        monkeypatch.setattr("services.project_review.call_groq", fake_call_groq)
        findings, called = await _review_chunk("app.py", "python", "eval(payload)", __import__("asyncio").Semaphore(CONCURRENCY_LIMIT))
        assert called is True
        assert findings == []

    def test_fake_identifier_and_fake_line_are_rejected_by_grounding(self):
        source = "overspendCategory = tx.category\n"
        fake_name = Issue(line=1, category="logic", issue="x", evidence="overshootCategory = tx.category", source="ai_quality")
        fake_line = Issue(line=9999, category="logic", issue="x", evidence="overspendCategory = tx.category", source="ai_quality")
        assert ground_issue(fake_name, source)[0] is False
        assert ground_issue(fake_line, source)[0] is False


class TestMalformedPython:
    def test_project_analysis_continues_after_bad_python_file(self):
        project = {
            "files": [
                {"path": "bad.py", "language": "python", "content": "def broken(:\n    pass"},
                {"path": "good.py", "language": "python", "content": "eval(payload)"},
            ]
        }
        analyzed = analyze_project(project)
        assert any("bad.py" in warning for warning in analyzed["warnings"])
        assert any(f["file"] == "good.py" and f["rule"] == "dangerous_eval" for f in analyzed["findings"])


class TestIdempotency:
    def test_repeated_analysis_does_not_accumulate_derived_metadata(self):
        project = {"files": [{"path": "app.py", "language": "python", "content": "import os\n\ndef f():\n    return 1"}]}
        first = analyze_project(project)
        second = analyze_project(first)
        third = analyze_project(second)
        assert len(third["imports"]) == 1
        assert len(third["functions"]) == 1
        assert len(third["structuralMetadata"]) == 1
        assert third["findings"] == []


class TestSecurityFalsePositives:
    def test_comments_and_documentation_examples_do_not_trigger_secret_rule(self):
        source = "# password = 'example-secret'\ntext = \"docs: api_key = 'fake-value'\""
        findings = run_rules("docs.py", "python", source)
        assert not any(f["rule"] == "hardcoded_secret" for f in findings)

    def test_static_url_is_not_ssrf_but_request_url_is(self):
        safe = "requests.get('https://api.example.com/health')"
        unsafe = "requests.get(request.args['url'])"
        assert not any(f["rule"] == "ssrf_untrusted_url" for f in run_rules("safe.py", "python", safe))
        assert any(f["rule"] == "ssrf_untrusted_url" for f in run_rules("unsafe.py", "python", unsafe))


class TestPerformance:
    def test_500_file_static_analysis_completes_quickly(self):
        project = {
            "files": [
                {"path": f"f{i}.py", "language": "python", "content": "def f():\n    return 1"}
                for i in range(500)
            ]
        }
        start = time.perf_counter()
        analyzed = analyze_project(project)
        elapsed = time.perf_counter() - start
        assert len(analyzed["functions"]) == 500
        assert elapsed < 5
