"""Password hashing, email normalization, and JWT session handling.

Kept as one small module rather than split hashing/tokens/deps files --
nothing here is reused outside the auth flow, so there's no reason to
scatter it.
"""

import re
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash
from email_validator import validate_email, EmailNotValidError
from fastapi import Cookie, HTTPException, status

from config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET

COOKIE_NAME = "sage_session"

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 8


class AuthError(Exception):
    """Raised for any signup/login input problem; routers turn this into a generic 400."""


def normalize_email(raw: str) -> str:
    """Trims, validates format, and case-normalizes. Raises AuthError on anything invalid."""
    try:
        result = validate_email((raw or "").strip(), check_deliverability=False)
    except EmailNotValidError:
        raise AuthError("Enter a valid email address")
    return result.normalized.lower()


def validate_password_strength(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
        raise AuthError("Password must contain both letters and numbers")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHash):
        return False


def _require_secret() -> str:
    # Lazy check (mirrors db.mongo's _require_db): importing this module
    # must not crash a process that hasn't configured auth yet, but issuing
    # or verifying a real token always must have a real secret behind it.
    if not JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET is not configured. Set it in the environment before using authentication."
        )
    return JWT_SECRET


def create_session_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, _require_secret(), algorithm=JWT_ALGORITHM)


def decode_session_token(token: str) -> str | None:
    """Returns the user id (sub) if the token is valid, else None. Never raises."""
    try:
        payload = jwt.decode(token, _require_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) and sub else None


async def get_current_user(session_token: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    """Reusable FastAPI dependency: 401 on any missing/invalid/expired/tampered
    token, or on a token for a user that no longer exists. Every protected
    route pulls identity from here -- never from a request body/query param."""
    from db.mongo import get_user_by_id  # local import: avoid a module-load cycle with db.mongo

    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if not session_token:
        raise unauthorized
    user_id = decode_session_token(session_token)
    if not user_id:
        raise unauthorized
    user = await get_user_by_id(user_id)
    if user is None:
        raise unauthorized
    return user
