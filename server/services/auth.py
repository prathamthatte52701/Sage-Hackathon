"""Password hashing, email normalization, and server-side opaque sessions.

Phase 1 authentication foundation.

Sessions are server-controlled opaque tokens:

    browser --HttpOnly cookie--> random opaque token
                              --> server hashes token (HMAC-SHA256, SESSION_SECRET)
                              --> Mongo session record (token_hash, expiry, metadata)
                              --> user_id

The raw token is never persisted. Only its HMAC digest is stored, so a
database read alone cannot forge a valid token. This model (vs a stateless
self-signed JWT) gives the server real revocation authority, which Phase 2
device/session management and "logout all devices" depend on.

DB access is imported lazily inside each function so tests can monkeypatch
``db.mongo.*`` and have it take effect (otherwise the module-level binding
would shadow the patch).
"""

import hmac
import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Optional

import re
from email_validator import EmailNotValidError, validate_email
from fastapi import Cookie, HTTPException, status

from config import (
    AUTH_ENABLED,
    COOKIE_SECURE,
    DEMO_USER_ID,
    SESSION_EXPIRE_MINUTES,
    SESSION_SECRET,
    VERIFICATION_TOKEN_MINUTES,
)

COOKIE_NAME = "sage_session"
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 200
_hasher = None


def _get_hasher():
    # Imported lazily so the module is importable without argon2 at import time
    # in unrelated tooling; argon2-cffi is a hard dependency of the app.
    global _hasher
    if _hasher is None:
        from argon2 import PasswordHasher

        _hasher = PasswordHasher()
    return _hasher


class AuthError(Exception):
    """Raised for invalid signup/login input."""


def normalize_email(raw: str) -> str:
    try:
        result = validate_email((raw or "").strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise AuthError("Enter a valid email address") from exc
    return result.normalized.lower()


def validate_password_strength(password: str) -> None:
    if not isinstance(password, str):
        raise AuthError("Password must be a string")
    # Reject whitespace-only / empty and enforce a sane minimum length. We
    # intentionally do NOT require composition rules (letters+numbers, etc.):
    # they push users to predictable patterns and weaken passphrases. Length
    # is the dominant factor; we avoid exposing a detailed rule list that would
    # aid account probing.
    if len(password.strip()) == 0:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AuthError("Password is too long")


def hash_password(password: str) -> str:
    return _get_hasher().hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    from argon2.exceptions import InvalidHash, VerifyMismatchError

    try:
        return _get_hasher().verify(password_hash, password)
    except (VerifyMismatchError, InvalidHash):
        return False


def _require_secret() -> str:
    if not SESSION_SECRET:
        raise RuntimeError(
            "SESSION_SECRET (or JWT_SECRET fallback) is not configured. "
            "Set it before enabling authentication."
        )
    return SESSION_SECRET


def _hash_token(token: str) -> str:
    """Stable server-side digest of a raw opaque token.

    HMAC binds the digest to SESSION_SECRET so a leaked DB (token_hash column)
    cannot be used to forge tokens without the secret.
    """
    return hmac.new(
        _require_secret().encode("utf-8"),
        token.encode("utf-8"),
        sha256,
    ).hexdigest()


def _as_aware_utc(dt):
    """Normalize a datetime for comparison.

    Mongo (without tz_aware clients) returns UTC timestamps as naive datetimes.
    Treat naive values as UTC so comparisons against timezone-aware ``now``
    never raise and never drift.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)


async def create_session(user_id: str, metadata: Optional[dict] = None) -> str:
    """Issue a new opaque session and return the RAW token (cookie-bound).

    The raw token is returned to the caller to set on the HttpOnly cookie and
    is never persisted. Only its HMAC digest is stored.
    """
    from db.mongo import create_session_record

    raw = generate_opaque_token()
    token_hash = _hash_token(raw)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=SESSION_EXPIRE_MINUTES)
    await create_session_record(token_hash, user_id, expires_at, metadata)
    return raw


async def create_verification_token(user_id: str) -> str:
    """Issue a single-use, expiring email-verification token (raw value).

    Persists only the HMAC digest. The raw value is returned for delivery via
    the mail abstraction and must never be logged or returned via API.
    """
    from db.mongo import create_email_verification

    raw = generate_opaque_token()
    token_hash = _hash_token(raw)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_TOKEN_MINUTES)
    await create_email_verification(user_id, token_hash, expires_at)
    return raw


async def consume_verification_token(raw_token: str) -> Optional[str]:
    """Validate and consume a raw verification token.

    Returns the user_id on success, or None if the token is unknown, expired,
    or already used. The token is marked used atomically on success.
    """
    from db.mongo import (
        get_email_verification,
        mark_email_verified,
        mark_verification_used,
    )

    if not raw_token:
        return None
    token_hash = _hash_token(raw_token)
    record = await get_email_verification(token_hash)
    if record is None:
        return None
    if record.get("used_at") is not None:
        return None
    expires_at = _as_aware_utc(record.get("expires_at"))
    if expires_at is None or expires_at <= datetime.now(timezone.utc):
        return None
    user_id = record.get("user_id")
    await mark_email_verified(user_id)
    await mark_verification_used(record["_id"])
    return user_id


def _unauthorized():
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def revoke_session_for_token(raw_token: Optional[str]) -> None:
    """Best-effort revocation of the server-side session behind a raw cookie token."""
    if not raw_token:
        return
    from db.mongo import revoke_session_by_token_hash

    await revoke_session_by_token_hash(_hash_token(raw_token))


async def get_current_user(session_token: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    """Require a valid session and resolve its user server-side.

    The session token is supplied only via the HttpOnly cookie; the frontend
    can never present an identity. We hash the token, look up the server-side
    session, verify it is live (not expired, not revoked), then load the user
    and confirm it is active.
    """
    from db.mongo import get_session, get_user_by_id, update_session_last_seen

    if not session_token:
        raise _unauthorized()
    token_hash = _hash_token(session_token)
    session = await get_session(token_hash)
    if session is None:
        raise _unauthorized()
    if session.get("revoked_at") is not None:
        raise _unauthorized()
    expires_at = _as_aware_utc(session.get("expires_at"))
    if expires_at is None or expires_at <= datetime.now(timezone.utc):
        raise _unauthorized()
    user = await get_user_by_id(session["user_id"])
    if user is None:
        raise _unauthorized()
    if user.get("status") != "active":
        raise _unauthorized()
    # Bounded last_seen update (only if older than 5 minutes)
    await update_session_last_seen(token_hash)
    # Never hand the password hash to callers/routers.
    user.pop("password_hash", None)
    return user


async def get_request_user(session_token: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    """Central identity dependency for all CODE MASTER AI workspaces.

    Demo mode has one server-owned identity, while enabled auth delegates to
    the strict opaque-session validation path.
    """
    if not AUTH_ENABLED:
        return {"_id": DEMO_USER_ID, "email": "demo@sage.local", "demo_mode": True}
    return await get_current_user(session_token)
    """Like get_current_user but also returns the session record for current-session identification."""
    from db.mongo import get_session, get_user_by_id, update_session_last_seen

    if not session_token:
        raise _unauthorized()
    token_hash = _hash_token(session_token)
    session = await get_session(token_hash)
    if session is None:
        raise _unauthorized()
    if session.get("revoked_at") is not None:
        raise _unauthorized()
    expires_at = _as_aware_utc(session.get("expires_at"))
    if expires_at is None or expires_at <= datetime.now(timezone.utc):
        raise _unauthorized()
    user = await get_user_by_id(session["user_id"])
    if user is None:
        raise _unauthorized()
    if user.get("status") != "active":
        raise _unauthorized()
    # Bounded last_seen update (only if older than 5 minutes)
    await update_session_last_seen(token_hash)
    user.pop("password_hash", None)
    # Return both user and session (without token_hash)
    safe_session = {
        "session_id": session["_id"],
        "created_at": session.get("created_at"),
        "last_seen_at": session.get("last_seen_at"),
        "expires_at": session.get("expires_at"),
        "device_label": session.get("device_label"),
        "user_agent_summary": session.get("user_agent_summary"),
    }
    return user, safe_session


async def list_active_sessions(user_id: str) -> list[dict]:
    """List all active sessions for a user with safe fields only."""
    from db.mongo import get_active_sessions_for_user

    sessions = await get_active_sessions_for_user(user_id)
    return [
        {
            "session_id": s["_id"],
            "created_at": s.get("created_at"),
            "last_seen_at": s.get("last_seen_at"),
            "expires_at": s.get("expires_at"),
            "device_label": s.get("device_label"),
            "user_agent_summary": s.get("user_agent_summary"),
        }
        for s in sessions
    ]


async def revoke_session(session_id: str, user_id: str) -> bool:
    """Revoke a specific session by ID, only if owned by user_id."""
    from db.mongo import revoke_session as mongo_revoke_session

    return await mongo_revoke_session(session_id, user_id)


async def revoke_all_sessions_for_user(user_id: str) -> int:
    """Revoke all active sessions for a user. Returns count."""
    from db.mongo import revoke_all_sessions_for_user as mongo_revoke_all

    return await mongo_revoke_all(user_id)


async def update_last_seen(session_token: str) -> None:
    """Update last_seen_at for the current session (bounded writes)."""
    if not session_token:
        return
    from db.mongo import update_session_last_seen

    await update_session_last_seen(_hash_token(session_token))
