"""Phase 3.10 certification: SEC-WEAK-CRYPTO-RANDOM."""

from services.analyzers.rules import run_rules
from services.security_rules import to_closed_world_findings


def _crypto_findings(code: str, language: str = "python") -> list[dict]:
    findings = to_closed_world_findings(run_rules("repository/app.py", language, code))
    return [finding for finding in findings if finding["rule_id"] == "SEC-WEAK-CRYPTO-RANDOM"]


def test_python_md5_password_hash_is_reported():
    findings = _crypto_findings("password_hash = hashlib.md5(password.encode()).hexdigest()")

    assert len(findings) == 1
    assert findings[0]["cwe"] == "CWE-330"


def test_python_sha1_token_and_predictable_reset_token_are_reported():
    code = "token_digest = hashlib.sha1(token.encode()).hexdigest()\nreset_token = random.choice(alphabet)"

    assert len(_crypto_findings(code)) == 2


def test_python_checksum_and_non_security_random_are_silent():
    code = "checksum = hashlib.md5(file_bytes).hexdigest()\ncolor = random.choice(colors)"

    assert _crypto_findings(code) == []


def test_python_comments_and_strings_are_silent():
    code = "# password_hash = hashlib.md5(password).hexdigest()\nexample = \"token = random.choice(chars)\""

    assert _crypto_findings(code) == []


def test_javascript_weak_hash_and_random_token_are_reported():
    code = "const passwordHash = crypto.createHash('sha1');\nconst sessionToken = Math.random().toString();"

    assert len(_crypto_findings(code, "javascript")) == 2


def test_javascript_non_security_and_comments_are_silent():
    code = "const color = Math.random();\n// const token = Math.random();"

    assert _crypto_findings(code, "typescript") == []


def test_repeated_analysis_is_deterministic():
    runs = [_crypto_findings("password_hash = hashlib.md5(password).hexdigest()") for _ in range(10)]

    assert all(run == runs[0] for run in runs)
