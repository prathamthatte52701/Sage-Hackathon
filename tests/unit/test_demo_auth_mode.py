import pytest
from fastapi import HTTPException

import main
from services import auth


@pytest.mark.asyncio
async def test_demo_mode_uses_one_server_owned_identity(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    monkeypatch.setattr(auth, "DEMO_USER_ID", "demo-user")

    user = await auth.get_request_user(session_token=None)

    assert user == {"_id": "demo-user", "email": "demo@sage.local", "demo_mode": True}


@pytest.mark.asyncio
async def test_enabled_auth_keeps_strict_cookie_validation(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)

    with pytest.raises(HTTPException) as exc_info:
        await auth.get_request_user(session_token=None)

    assert exc_info.value.status_code == 401


def test_demo_mode_does_not_register_login_routes():
    assert main.AUTH_ENABLED is False
    assert "/api/auth/login" not in {getattr(route, "path", None) for route in main.app.routes}
