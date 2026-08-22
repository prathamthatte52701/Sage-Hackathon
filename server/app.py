"""Compatibility shim for legacy `uvicorn app:app` start commands.

The real application entrypoint remains main.py.
"""

from main import app
