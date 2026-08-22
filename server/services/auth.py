"""Password hashing, email normalization, and JWT session handling."""

import re
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError
from email_validator import EmailNotValidError, validate_email
from fastapi import Cookie, HTTPException, status

from config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET

COOKIE_NAME = "sage_session"
MIN_PASSWORD_LENGTH = 8
_hasher = PasswordHasher()


class AuthError(Exception):
    """Raised for invalid signup/login input."""


def normalize_email(raw: str) -> str:
    try:
        result = validate_email((raw or "").strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise AuthError("Enter a valid email address") from exc
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
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not configured. Set it before using authentication.")
    return JWT_SECRET


def create_session_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES)},
        _require_secret(),
        algorithm=JWT_ALGORITHM,
    )


def decode_session_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, _require_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) and sub else None


async def get_current_user(session_token: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    """Require a valid session and resolve its user server-side."""
    from db.mongo import get_user_by_id

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
