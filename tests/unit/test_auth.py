import jwt
import pytest
from fastapi import HTTPException, Response
from pymongo.errors import DuplicateKeyError

import routers.auth as auth_router
from config import JWT_ALGORITHM, JWT_SECRET
from services import auth as auth_service


# ---------------------------------------------------------------- Phase 1: password/email primitives

def test_normalize_email_trims_and_lowercases():
    assert auth_service.normalize_email("  User@Example.COM  ") == "user@example.com"


def test_normalize_email_rejects_invalid_format():
    with pytest.raises(auth_service.AuthError):
        auth_service.normalize_email("not-an-email")


@pytest.mark.parametrize("password", ["short1", "nodigitshere", "12345678"])
def test_validate_password_strength_rejects_weak(password):
    with pytest.raises(auth_service.AuthError):
        auth_service.validate_password_strength(password)


def test_validate_password_strength_accepts_valid():
    auth_service.validate_password_strength("goodpass123")  # no raise


def test_hash_password_never_stores_plaintext():
    hashed = auth_service.hash_password("goodpass123")
    assert hashed != "goodpass123"
    assert hashed.startswith("$argon2")


def test_verify_password_roundtrip():
    hashed = auth_service.hash_password("goodpass123")
    assert auth_service.verify_password("goodpass123", hashed) is True
    assert auth_service.verify_password("wrongpass123", hashed) is False


# ---------------------------------------------------------------- Phase 3: JWT session tokens

def test_create_and_decode_session_token_roundtrip():
    token = auth_service.create_session_token("user-123")
    assert auth_service.decode_session_token(token) == "user-123"


def test_decode_session_token_rejects_garbage():
    assert auth_service.decode_session_token("not-a-jwt") is None


def test_decode_session_token_rejects_tampered_signature():
    token = auth_service.create_session_token("user-123")
    tampered = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")
    assert auth_service.decode_session_token(tampered) is None


def test_decode_session_token_rejects_expired():
    import datetime as dt

    payload = {
        "sub": "user-123",
        "iat": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=120),
        "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=60),
    }
    expired = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    assert auth_service.decode_session_token(expired) is None


def test_decode_session_token_rejects_alg_none():
    # Never accept an unsigned/none-alg token even if it carries a valid sub.
    forged = jwt.encode({"sub": "user-123"}, "", algorithm="none")
    assert auth_service.decode_session_token(forged) is None


@pytest.mark.asyncio
async def test_get_current_user_requires_cookie():
    with pytest.raises(HTTPException) as exc_info:
        await auth_service.get_current_user(session_token=None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_rejects_invalid_token():
    with pytest.raises(HTTPException) as exc_info:
        await auth_service.get_current_user(session_token="garbage")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_rejects_deleted_user(monkeypatch):
    async def fake_get_user_by_id(user_id):
        return None

    monkeypatch.setattr("db.mongo.get_user_by_id", fake_get_user_by_id)
    token = auth_service.create_session_token("ghost-user")
    with pytest.raises(HTTPException) as exc_info:
        await auth_service.get_current_user(session_token=token)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_returns_user_on_valid_token(monkeypatch):
    async def fake_get_user_by_id(user_id):
        return {"_id": user_id, "email": "a@example.com"}

    monkeypatch.setattr("db.mongo.get_user_by_id", fake_get_user_by_id)
    token = auth_service.create_session_token("user-123")
    user = await auth_service.get_current_user(session_token=token)
    assert user["_id"] == "user-123"


# ---------------------------------------------------------------- Phase 2: signup/login endpoints

from models.schemas import LoginRequest, SignupRequest  # noqa: E402


@pytest.mark.asyncio
async def test_signup_success(monkeypatch):
    created = {}

    async def fake_create_user(email, password_hash):
        created["email"] = email
        created["password_hash"] = password_hash
        return "new-user-id"

    async def fake_get_user_by_email(email):
        return {"_id": "new-user-id", "email": email, "created_at": None}

    monkeypatch.setattr(auth_router, "create_user", fake_create_user)
    monkeypatch.setattr(auth_router, "get_user_by_email", fake_get_user_by_email)

    result = await auth_router.signup(
        SignupRequest(email="New@Example.com", password="goodpass123"), Response()
    )

    assert result["id"] == "new-user-id"
    assert result["email"] == "new@example.com"
    assert "password_hash" not in result
    assert "password" not in result
    assert created["email"] == "new@example.com"
    assert created["password_hash"] != "goodpass123"  # never stored plaintext


@pytest.mark.asyncio
async def test_signup_rejects_invalid_email():
    response = await auth_router.signup(
        SignupRequest(email="not-an-email", password="goodpass123"), Response()
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_signup_rejects_weak_password():
    response = await auth_router.signup(
        SignupRequest(email="a@example.com", password="weak"), Response()
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_signup_rejects_duplicate_email(monkeypatch):
    async def fake_create_user(email, password_hash):
        raise DuplicateKeyError("duplicate")

    monkeypatch.setattr(auth_router, "create_user", fake_create_user)

    response = await auth_router.signup(
        SignupRequest(email="dupe@example.com", password="goodpass123"), Response()
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_login_success(monkeypatch):
    stored_hash = auth_service.hash_password("goodpass123")

    async def fake_get_user_by_email(email):
        return {"_id": "user-1", "email": email, "password_hash": stored_hash, "created_at": None}

    monkeypatch.setattr(auth_router, "get_user_by_email", fake_get_user_by_email)

    result = await auth_router.login(
        LoginRequest(email="a@example.com", password="goodpass123"), Response()
    )
    assert result["id"] == "user-1"
    assert "password_hash" not in result


@pytest.mark.asyncio
async def test_login_wrong_password_and_unknown_account_return_identical_error(monkeypatch):
    """Never reveal which one was wrong -- both cases must be indistinguishable."""
    stored_hash = auth_service.hash_password("goodpass123")

    async def fake_get_user_by_email_known(email):
        return {"_id": "user-1", "email": email, "password_hash": stored_hash, "created_at": None}

    async def fake_get_user_by_email_unknown(email):
        return None

    monkeypatch.setattr(auth_router, "get_user_by_email", fake_get_user_by_email_known)
    wrong_password_response = await auth_router.login(
        LoginRequest(email="a@example.com", password="wrongpass123"), Response()
    )

    monkeypatch.setattr(auth_router, "get_user_by_email", fake_get_user_by_email_unknown)
    unknown_account_response = await auth_router.login(
        LoginRequest(email="ghost@example.com", password="whatever123"), Response()
    )

    assert wrong_password_response.status_code == 401
    assert unknown_account_response.status_code == 401
    assert wrong_password_response.body == unknown_account_response.body


@pytest.mark.asyncio
async def test_logout_clears_cookie():
    response = Response()
    result = await auth_router.logout(response)
    assert result == {"status": "ok"}
    assert "sage_session" in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_me_returns_current_user():
    result = await auth_router.me(current_user={"_id": "u1", "email": "a@example.com", "created_at": None})
    assert result["id"] == "u1"
    assert "password_hash" not in result
