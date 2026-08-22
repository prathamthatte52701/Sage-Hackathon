"""Render compatibility entrypoint.

The canonical ASGI app lives in server/main.py and Render should start it
with `uvicorn main:app` from rootDir=server. This shim keeps older/manual
Render services that still run `uvicorn app:app` from failing while that
dashboard setting is corrected.
"""

from pathlib import Path
import sys

SERVER_DIR = Path(__file__).resolve().parent / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from main import app  # noqa: E402
