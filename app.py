"""Render compatibility entrypoint.

The canonical ASGI app lives in server/main.py and Render should start it
with `uvicorn main:app` from rootDir=server. This shim also keeps older/manual
Render services that still run `uvicorn app:app` or `uvicorn app.main:app`
from failing while that dashboard setting is corrected.
"""

from pathlib import Path
import sys

SERVER_DIR = Path(__file__).resolve().parent / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# Let `import app.main` resolve to server/app/main.py even though this file is
# also importable as the top-level `app` module.
__path__ = [str(SERVER_DIR / "app")]

from main import app  # noqa: E402
