"""Phase 7: engineering standards library.

Each standard cites a real external source (OWASP/CWE/official docs) so the
system can always answer "why does this matter" with a citation, not a
made-up rule. Looked up by category + language and injected into the Phase 6
reasoning prompt, and referenced in the Phase 4 score breakdown.
"""

STANDARDS = [
    # security
    {
        "id": "SEC-01",
        "category": "security",
        "language": "any",
        "title": "No hardcoded credentials",
        "description": "Secrets, API keys, and passwords must never be committed in source code.",
        "detectionMethod": "regex: password/secret/api_key/token assignment to a literal string",
        "evidenceSource": "OWASP Top 10 A07:2021 - Identification and Authentication Failures / CWE-798",
        "confidence": 0.95,
    },
    {
        "id": "SEC-02",
        "category": "security",
        "language": "any",
        "title": "Parameterized queries only",
        "description": "SQL must never be built via string concatenation or f-strings with user input.",
        "detectionMethod": "regex: SQL keyword adjacent to string concatenation or interpolation",
        "evidenceSource": "OWASP Top 10 A03:2021 - Injection / CWE-89",
        "confidence": 0.9,
    },
    {
        "id": "SEC-03",
        "category": "security",
        "language": "python,javascript,typescript",
        "title": "No dynamic code execution on untrusted input",
        "description": "eval()/exec() on untrusted input allows arbitrary code execution.",
        "detectionMethod": "regex: eval(/exec( call",
        "evidenceSource": "CWE-95: Improper Neutralization of Directives in Dynamically Evaluated Code",
        "confidence": 0.9,
    },
    {
        "id": "SEC-04",
        "category": "security",
        "language": "python,javascript,typescript",
        "title": "Never shell out to unsanitized input",
        "description": "subprocess calls with shell=True (Python) or child_process.exec/execSync (Node) with unsanitized input risk command injection.",
        "detectionMethod": "regex: subprocess.*shell=True / child_process.exec(Sync)?(",
        "evidenceSource": "CWE-78: OS Command Injection",
        "confidence": 0.85,
    },
    {
        "id": "SEC-05",
        "category": "security",
        "language": "any",
        "title": "TLS certificate verification must stay enabled",
        "description": "Disabling TLS verification exposes traffic to man-in-the-middle attacks.",
        "detectionMethod": "regex: verify=False / NODE_TLS_REJECT_UNAUTHORIZED=0",
        "evidenceSource": "OWASP Top 10 A02:2021 - Cryptographic Failures / CWE-295",
        "confidence": 0.85,
    },
    {
        "id": "SEC-06",
        "category": "security",
        "language": "python,javascript,typescript",
        "title": "Avoid unsafe deserialization of untrusted data",
        "description": "pickle.loads and unsafe yaml.load (Python), or node-serialize/unserialize (Node), can execute arbitrary code from crafted input.",
        "detectionMethod": "regex: pickle.loads / yaml.load without SafeLoader / node-serialize / unserialize(",
        "evidenceSource": "CWE-502: Deserialization of Untrusted Data",
        "confidence": 0.85,
    },
    # code_quality
    {
        "id": "CQ-01",
        "category": "code_quality",
        "language": "python,javascript,typescript",
        "title": "Never use empty or catch-all exception handling",
        "description": "Bare except: (Python) or an empty catch {} block (JS/TS) silently swallows all exceptions, including real bugs.",
        "detectionMethod": "regex: bare except: clause / empty catch {} block",
        "evidenceSource": "PEP 8 - Programming Recommendations",
        "confidence": 0.9,
    },
    {
        "id": "CQ-02",
        "category": "code_quality",
        "language": "any",
        "title": "Resolve TODO/FIXME markers before release",
        "description": "Unresolved TODO/FIXME markers indicate known incomplete or fragile code.",
        "detectionMethod": "regex: TODO/FIXME comment marker",
        "evidenceSource": "Internal engineering hygiene standard",
        "confidence": 0.6,
    },
    {
        "id": "CQ-03",
        "category": "code_quality",
        "language": "any",
        "title": "Keep functions focused and named for their purpose",
        "description": "Long, multi-responsibility functions are harder to test and reason about.",
        "detectionMethod": "not currently automated — manual/LLM review only",
        "evidenceSource": "Clean Code (Martin) - Functions chapter",
        "confidence": 0.4,
    },
    # architecture
    {
        "id": "ARCH-01",
        "category": "architecture",
        "language": "any",
        "title": "Separate concerns across modules",
        "description": "Business logic, data access, and presentation should live in distinct modules.",
        "detectionMethod": "not currently automated — no deterministic check implemented yet",
        "evidenceSource": "Separation of Concerns (Dijkstra)",
        "confidence": 0.3,
    },
    {
        "id": "ARCH-02",
        "category": "architecture",
        "language": "any",
        "title": "Avoid circular dependencies between modules",
        "description": "Circular imports make code harder to test in isolation and can cause runtime errors.",
        "detectionMethod": "not currently automated — would require full import graph analysis",
        "evidenceSource": "General software architecture best practice",
        "confidence": 0.3,
    },
    # testing
    {
        "id": "TEST-01",
        "category": "testing",
        "language": "any",
        "title": "Every project should have automated tests",
        "description": "Projects with zero detected test files have no automated regression safety net.",
        "detectionMethod": "file discovery: test_*.py, *.test.js, tests/ directory, etc.",
        "evidenceSource": "General software engineering best practice",
        "confidence": 0.7,
    },
    {
        "id": "TEST-02",
        "category": "testing",
        "language": "any",
        "title": "Critical security fixes should be covered by a regression test",
        "description": "A fix without a test can silently regress in a future change.",
        "detectionMethod": "not currently automated — requires linking fixes to test coverage",
        "evidenceSource": "General software engineering best practice",
        "confidence": 0.3,
    },
    {
        "id": "TEST-03",
        "category": "testing",
        "language": "any",
        "title": "Tests should be discoverable by standard naming conventions",
        "description": "Non-standard test file naming prevents test runners from finding tests automatically.",
        "detectionMethod": "file discovery against known test naming conventions",
        "evidenceSource": "pytest / Jest discovery conventions",
        "confidence": 0.6,
    },
    # api_design
    {
        "id": "API-01",
        "category": "api_design",
        "language": "any",
        "title": "Validate all external input at the boundary",
        "description": "Input validation should happen at the API boundary, not deep inside business logic.",
        "detectionMethod": "not currently automated — no deterministic check implemented yet",
        "evidenceSource": "OWASP API Security Top 10",
        "confidence": 0.3,
    },
    {
        "id": "API-02",
        "category": "api_design",
        "language": "any",
        "title": "Never leak raw stack traces or exception text to API clients",
        "description": "Error responses should be clean, structured messages, not raw internal exception text.",
        "detectionMethod": "not currently automated — requires runtime response inspection",
        "evidenceSource": "OWASP API Security Top 10 - API8:2023 Security Misconfiguration",
        "confidence": 0.3,
    },
    # performance
    {
        "id": "PERF-01",
        "category": "performance",
        "language": "any",
        "title": "Avoid obvious N+1 query patterns",
        "description": "Looping over a collection and querying inside the loop is a common performance anti-pattern.",
        "detectionMethod": "not currently automated — no deterministic check implemented yet",
        "evidenceSource": "General database performance best practice",
        "confidence": 0.3,
    },
    # production_readiness
    {
        "id": "PROD-01",
        "category": "production_readiness",
        "language": "any",
        "title": "Ship with a deployment configuration",
        "description": "A project without a Dockerfile/CI config/deployment manifest is not demonstrably deployable.",
        "detectionMethod": "file discovery: Dockerfile, docker-compose.yml, render.yaml, vercel.json, Procfile, .github/workflows/",
        "evidenceSource": "General DevOps best practice (12-factor app)",
        "confidence": 0.6,
    },
]


def get_standards_for(category: str, language: str | None = None) -> list[dict]:
    results = []
    for s in STANDARDS:
        if s["category"] != category:
            continue
        if s["language"] == "any" or language is None:
            results.append(s)
        elif language in s["language"].split(","):
            results.append(s)
    return results


def get_standard_by_id(standard_id: str) -> dict | None:
    for s in STANDARDS:
        if s["id"] == standard_id:
            return s
    return None
