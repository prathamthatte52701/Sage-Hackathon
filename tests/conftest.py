import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import pytest

import db.mongo as _mongo_module


@pytest.fixture(autouse=True)
def _fresh_db_client_per_test():
    """pytest-asyncio gives each test function its own event loop by
    default. db.mongo's get_db() lazily constructs a singleton Motor client
    bound to whichever loop is running the FIRST time it's called -- correct
    for a single long-lived app process (the real FastAPI app), but across
    tests with different loops that stale client causes "attached to a
    different loop" errors on the second+ test using it, which callers like
    retrieve_knowledge's broad except then silently swallow as a fallback.
    Reset before every test so get_db() reconstructs fresh against that
    test's own loop."""
    _mongo_module._client = None
    _mongo_module.db = None
    _mongo_module.fs_bucket = None
    yield
