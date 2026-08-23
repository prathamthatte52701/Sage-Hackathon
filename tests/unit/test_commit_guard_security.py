import pytest

from services.commit_guard_security import compute_security_delta

SAFE = "def add(a, b):\n    return a + b\n"

# Same fixture shape as test_analyzer_rules.py's hardcoded-secret positive case.
SECRET = "API_KEY = 'abcdef12345'\n"

# subprocess_shell_true, from analyzers/rules.py: subprocess call with shell=True.
SHELL_TRUE = (
    "import subprocess\n"
    "def run(cmd):\n"
    "    subprocess.run(cmd, shell=True)\n"
)

SHELL_TRUE_MOVED = (
    "import subprocess\n"
    "\n"
    "\n"
    "def run(cmd):\n"
    "    # a couple of extra lines pushed the call further down\n"
    "    x = 1\n"
    "    subprocess.run(cmd, shell=True)\n"
)


@pytest.mark.asyncio
async def test_new_finding_introduced_at_head():
    result = await compute_security_delta({"app.py": SAFE}, {"app.py": SECRET})
    assert len(result["new"]) == 1
    assert result["new"][0]["rule_id"] == "SEC-HARDCODED-SECRET"
    assert result["resolved"] == []
    assert result["persisting"] == []


@pytest.mark.asyncio
async def test_finding_resolved_at_head():
    result = await compute_security_delta({"app.py": SECRET}, {"app.py": SAFE})
    assert result["new"] == []
    assert len(result["resolved"]) == 1
    assert result["resolved"][0]["rule_id"] == "SEC-HARDCODED-SECRET"
    assert result["persisting"] == []


@pytest.mark.asyncio
async def test_persisting_finding_survives_line_shift():
    result = await compute_security_delta({"app.py": SHELL_TRUE}, {"app.py": SHELL_TRUE_MOVED})
    assert result["new"] == []
    assert result["resolved"] == []
    assert len(result["persisting"]) == 1
    assert result["persisting"][0]["rule_id"] == "SEC-COMMAND-INJECTION"


@pytest.mark.asyncio
async def test_persisting_finding_survives_rename():
    result = await compute_security_delta(
        {"old_name.py": SHELL_TRUE},
        {"new_name.py": SHELL_TRUE},
        renamed_paths={"new_name.py": "old_name.py"},
    )
    assert result["new"] == []
    assert result["resolved"] == []
    assert len(result["persisting"]) == 1
    assert result["persisting"][0]["file"] == "new_name.py"


@pytest.mark.asyncio
async def test_empty_snapshots_no_crash():
    result = await compute_security_delta({}, {})
    assert result["new"] == []
    assert result["resolved"] == []
    assert result["persisting"] == []
    assert result["base_findings"] == []
    assert result["head_findings"] == []


@pytest.mark.asyncio
async def test_unrelated_findings_both_resolved_and_new():
    # Different rule entirely on each side, same file -- must not be merged
    # by a signature that's too loose.
    result = await compute_security_delta({"app.py": SECRET}, {"app.py": SHELL_TRUE})
    assert len(result["new"]) == 1
    assert result["new"][0]["rule_id"] == "SEC-COMMAND-INJECTION"
    assert len(result["resolved"]) == 1
    assert result["resolved"][0]["rule_id"] == "SEC-HARDCODED-SECRET"
    assert result["persisting"] == []
