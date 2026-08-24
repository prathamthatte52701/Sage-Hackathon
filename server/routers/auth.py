from fastapi import APIRouter, Cookie, Depends, Response
from fastapi.responses import JSONResponse
from pymongo.errors import DuplicateKeyError

from config import COOKIE_SECURE, SESSION_EXPIRE_MINUTES
from db.mongo import (
    create_user,
    get_user_by_email,
)
from models.schemas import (
    LoginRequest,
    ResendVerificationRequest,
    SignupRequest,
    UserOut,
    VerifyEmailRequest,
)
from services.auth import (
    COOKIE_NAME,
    AuthError,
    consume_verification_token,
    create_session,
    create_verification_token,
    get_current_user,
    hash_password,
    normalize_email,
    revoke_session_for_token,
    validate_password_strength,
    verify_password,
)
from services.mail import dispatch_verification_email

router = APIRouter()

_GENERIC_AUTH_ERROR = {"error": "Invalid email or password"}
_SIGNUP_ERROR = {"error": "Could not create account, please try again"}
_VERIFY_ERROR = {"error": "Invalid or expired verification link"}


def _user_out(user: dict) -> dict:
    created_at = user.get("created_at")
    updated_at = user.get("updated_at")
    return {
        "id": user["_id"],
        "email": user["email"],
        "email_verified": bool(user.get("email_verified", False)),
        "role": user.get("role", "user"),
        "status": user.get("status", "active"),
        "created_at": created_at.isoformat() if created_at else "",
        "updated_at": updated_at.isoformat() if updated_at else "",
    }


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=SESSION_EXPIRE_MINUTES * 60,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


@router.post("/auth/signup", response_model=UserOut)
async def signup(payload: SignupRequest, response: Response):
    try:
        email_normalized = normalize_email(payload.email)
        validate_password_strength(payload.password)
    except AuthError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    try:
        user_id = await create_user(
            email=payload.email.strip(),
            email_normalized=email_normalized,
            password_hash=hash_password(payload.password),
        )
    except DuplicateKeyError:
        # Generic response: do not reveal that the email already exists.
        return JSONResponse(status_code=400, content=_SIGNUP_ERROR)
    except Exception:
        # Never log the password or token; only the error class is safe.
        print("[auth] signup error")
        return JSONResponse(status_code=500, content=_SIGNUP_ERROR)

    # Email verification foundation: issue a single-use, expiring token and
    # dispatch it through the mail abstraction. The raw token is never stored
    # or returned here.
    try:
        raw_token = await create_verification_token(user_id)
        await dispatch_verification_email(email_normalized, raw_token)
    except Exception:
        # Verification dispatch failure must not fail signup; the user can
        # resend later. Do not log the token.
        print("[auth] verification dispatch failed")

    # Auto-establish a session so the new user lands in the app immediately;
    # the UI shows a verify-your-email notice until verified.
    token = await create_session(user_id)
    _set_session_cookie(response, token)
    user = await get_user_by_email(email_normalized)
    return _user_out(user)


@router.post("/auth/login", response_model=UserOut)
async def login(payload: LoginRequest, response: Response):
    try:
        email_normalized = normalize_email(payload.email)
    except AuthError:
        return JSONResponse(status_code=401, content=_GENERIC_AUTH_ERROR)

    user = await get_user_by_email(email_normalized)
    if user is None or not verify_password(payload.password, user["password_hash"]):
        return JSONResponse(status_code=401, content=_GENERIC_AUTH_ERROR)

    # Disabled accounts are rejected with the same generic response as bad
    # credentials to avoid leaking account state.
    if user.get("status") != "active":
        return JSONResponse(status_code=401, content=_GENERIC_AUTH_ERROR)

    token = await create_session(user["_id"])
    _set_session_cookie(response, token)
    return _user_out(user)


@router.post("/auth/logout")
async def logout(response: Response, session_token: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    # Revoke the server-side session (if found) before clearing the cookie so a
    # captured cookie cannot be replayed after logout.
    await revoke_session_for_token(session_token)
    _clear_session_cookie(response)
    return {"status": "ok"}


@router.post("/auth/verify-email")
async def verify_email(payload: VerifyEmailRequest):
    user_id = await consume_verification_token(payload.token)
    if user_id is None:
        return JSONResponse(status_code=400, content=_VERIFY_ERROR)
    return {"status": "ok", "email_verified": True}


@router.post("/auth/resend-verification")
async def resend_verification(
    _payload: ResendVerificationRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["_id"]
    try:
        raw_token = await create_verification_token(user_id)
        await dispatch_verification_email(current_user.get("email", ""), raw_token)
    except Exception:
        print("[auth] resend verification dispatch failed")
        return JSONResponse(status_code=500, content={"error": "Could not send verification email"})
    return {"status": "ok"}


@router.get("/auth/me", response_model=UserOut)
async def me(current_user: dict = Depends(get_current_user)):
    return _user_out(current_user)
