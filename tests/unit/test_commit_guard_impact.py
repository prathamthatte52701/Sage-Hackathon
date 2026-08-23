import pytest

from services.commit_guard_impact import compute_blast_delta, detect_sensitive_areas

UTIL = "def add(a, b):\n    return a + b\n"

AUTH_ROUTE = (
    "from utils import add\n\n"
    "@router.post('/login')\n"
    "def login():\n"
    "    session = get_current_user()\n"
    "    return add(1, 2)\n"
)

ROUTE_TWO = (
    "from utils import add\n\n"
    "@router.get('/dashboard')\n"
    "def dashboard():\n"
    "    return add(2, 3)\n"
)

ADMIN_ROUTE = (
    "from utils import add\n\n"
    "@router.delete('/admin/users')\n"
    "def delete_user():\n"
    "    return add(3, 4)\n"
)


@pytest.mark.asyncio
async def test_auth_blast_increase_when_file_gains_route_dependents():
    base_snapshot = {
        "utils.py": UTIL,
        "routes_one.py": AUTH_ROUTE,
    }
    head_snapshot = {
        "utils.py": UTIL,
        "routes_one.py": AUTH_ROUTE,
        "routes_two.py": ROUTE_TWO,
        "admin_routes.py": ADMIN_ROUTE,
    }

    result = await compute_blast_delta(base_snapshot, head_snapshot, ["utils.py"])

    assert len(result["components"]) == 1
    entry = result["components"][0]
    assert entry["path"] == "utils.py"
    assert entry["after_dependents"] > entry["before_dependents"]
    assert entry["delta"] > 0
    assert result["summary"]["overall_delta"] > 0
    assert result["summary"]["affected_routes_after"] > result["summary"]["affected_routes_before"]


@pytest.mark.asyncio
async def test_isolated_utility_has_low_or_zero_delta():
    base_snapshot = {"utils.py": UTIL}
    head_snapshot = {"utils.py": UTIL + "\n# trivial comment change\n"}

    result = await compute_blast_delta(base_snapshot, head_snapshot, ["utils.py"])

    entry = result["components"][0]
    assert entry["delta"] == 0
    assert entry["before_dependents"] == 0
    assert entry["after_dependents"] == 0
    assert result["summary"]["overall_delta"] == 0


def test_detect_sensitive_areas_flags_authentication():
    head_snapshot = {"routes_one.py": AUTH_ROUTE}
    tags = detect_sensitive_areas(head_snapshot, ["routes_one.py"])
    assert "authentication" in tags


def test_detect_sensitive_areas_deterministic_order_repeated_call():
    head_snapshot = {"routes_one.py": AUTH_ROUTE, "admin_routes.py": ADMIN_ROUTE}
    changed = ["routes_one.py", "admin_routes.py"]
    first = detect_sensitive_areas(head_snapshot, changed)
    second = detect_sensitive_areas(head_snapshot, changed)
    assert first == second
    assert "authentication" in first
    assert "admin" in first


def test_detect_sensitive_areas_no_false_positive_on_plain_utility():
    head_snapshot = {"utils.py": UTIL}
    tags = detect_sensitive_areas(head_snapshot, ["utils.py"])
    assert tags == []


@pytest.mark.asyncio
async def test_compute_blast_delta_empty_changed_paths_docs_only_commit():
    result = await compute_blast_delta({}, {}, [])
    assert result["components"] == []
    assert result["summary"]["overall_before"] == 0
    assert result["summary"]["overall_after"] == 0
    assert result["summary"]["overall_delta"] == 0
    assert result["summary"]["affected_routes_before"] == 0
    assert result["summary"]["affected_routes_after"] == 0


@pytest.mark.asyncio
async def test_compute_blast_delta_newly_added_file_no_crash():
    base_snapshot = {}
    head_snapshot = {"new_module.py": UTIL}

    result = await compute_blast_delta(base_snapshot, head_snapshot, ["new_module.py"])

    assert len(result["components"]) == 1
    entry = result["components"][0]
    assert entry["path"] == "new_module.py"
    assert entry["before_score"] == 0
    assert entry["before_dependents"] == 0
    assert entry["after_score"] >= 0
