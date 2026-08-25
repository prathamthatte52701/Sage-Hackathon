from fastapi import APIRouter, Cookie, Depends, Request, Response
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
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
    ChangeEmailRequest,
)
from services.auth import (
    COOKIE_NAME,
    AuthError,
    change_user_email,
    consume_verification_token,
    consume_password_reset_token,
    create_password_reset_token,
    create_session,
    create_verification_token,
    get_current_user,
    hash_password,
    list_active_sessions,
    normalize_email,
    revoke_all_sessions_for_user,
    revoke_session,
    revoke_session_for_token,
    update_user_password,
    validate_password_strength,
    verify_password,
)
from services.mail import dispatch_verification_email, dispatch_password_reset_email

router = APIRouter()

_GENERIC_AUTH_ERROR = {"error": "Invalid email or password"}
_SIGNUP_ERROR = {"error": "Could not create account, please try again"}
_VERIFY_ERROR = {"error": "Invalid or expired verification link"}
_RESET_ERROR = {"error": "Invalid or expired reset link"}


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


def _extract_device_metadata(request: Request) -> dict:
    """Extract safe device metadata from request for session record."""
    user_agent = request.headers.get("user-agent", "")
    # Derive a simple label from user agent (display only, not for auth)
    device_label = "Unknown device"
    if "Mobile" in user_agent or "Android" in user_agent or "iPhone" in user_agent:
        if "Chrome" in user_agent:
            device_label = "Chrome on Mobile"
        elif "Safari" in user_agent:
            device_label = "Safari on Mobile"
        elif "Firefox" in user_agent:
            device_label = "Firefox on Mobile"
        else:
            device_label = "Mobile Browser"
    elif "Windows" in user_agent:
        if "Chrome" in user_agent:
            device_label = "Chrome on Windows"
        elif "Firefox" in user_agent:
            device_label = "Firefox on Windows"
        elif "Edg" in user_agent:
            device_label = "Edge on Windows"
        else:
            device_label = "Windows Browser"
    elif "Macintosh" in user_agent or "macOS" in user_agent:
        if "Chrome" in user_agent:
            device_label = "Chrome on macOS"
        elif "Safari" in user_agent:
            device_label = "Safari on macOS"
        elif "Firefox" in user_agent:
            device_label = "Firefox on macOS"
        else:
            device_label = "macOS Browser"
    elif "Linux" in user_agent:
        if "Chrome" in user_agent:
            device_label = "Chrome on Linux"
        elif "Firefox" in user_agent:
            device_label = "Firefox on Linux"
        else:
            device_label = "Linux Browser"

    # Hash IP for minimal metadata (privacy-preserving)
    from hashlib import sha256
    client_ip = request.client.host if request.client else "unknown"
    ip_hash = sha256(client_ip.encode()).hexdigest()[:16]

    return {
        "device_label": device_label,
        "user_agent_summary": user_agent[:200],  # Truncate for storage
        "created_ip_hash": ip_hash,
    }


@router.post("/auth/signup", response_model=UserOut)
async def signup(payload: SignupRequest, response: Response, request: Request = None):
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
    metadata = _extract_device_metadata(request) if request else None
    token = await create_session(user_id, metadata)
    _set_session_cookie(response, token)
    user = await get_user_by_email(email_normalized)
    return _user_out(user)


@router.post("/auth/login", response_model=UserOut)
async def login(payload: LoginRequest, response: Response, request: Request = None):
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

    metadata = _extract_device_metadata(request) if request else None
    token = await create_session(user["_id"], metadata)
    _set_session_cookie(response, token)
    return _user_out(user)


@router.post("/auth/logout")
async def logout(response: Response, session_token: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    # Revoke the server-side session (if found) before clearing the cookie so a
    # captured cookie cannot be replayed after logout.
    await revoke_session_for_token(session_token)
    _clear_session_cookie(response)
    return {"status": "ok"}


@router.get("/auth/sessions")
async def list_sessions(
    current_user: dict = Depends(get_current_user),
    session_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    """List all active sessions for the current user with current session indicator."""
    sessions = await list_active_sessions(current_user["_id"])
    current_token_hash = None
    if session_token:
        from services.auth import _hash_token

        current_token_hash = _hash_token(session_token)

    # Mark current session
    for s in sessions:
        s["is_current"] = s.get("session_id") == current_token_hash

    return {"sessions": sessions}


@router.delete("/auth/sessions/{session_id}")
async def revoke_session_endpoint(
    session_id: str,
    response: Response,
    current_user: dict = Depends(get_current_user),
    session_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    """Revoke a specific session by ID. If it's the current session, also logout."""
    user_id = current_user["_id"]

    # Check if this is the current session
    from services.auth import _hash_token

    current_token_hash = _hash_token(session_token) if session_token else None
    is_current = current_token_hash == session_id

    success = await revoke_session(session_id, user_id)

    if not success:
        # Session not found or not owned - return generic success to avoid enumeration
        return {"status": "ok"}

    if is_current:
        # Current session was revoked - clear cookie
        _clear_session_cookie(response)

    return {"status": "ok", "revoked_current": is_current}


@router.post("/auth/logout-all")
async def logout_all(
    response: Response,
    current_user: dict = Depends(get_current_user),
):
    """Revoke all sessions for the current user and clear cookie."""
    user_id = current_user["_id"]
    count = await revoke_all_sessions_for_user(user_id)
    _clear_session_cookie(response)
    return {"status": "ok", "revoked_count": count}


@router.post("/auth/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest):
    """Issue a password reset token for the given email.

    Always returns generic success to prevent email enumeration.
    """
    try:
        email_normalized = normalize_email(payload.email)
    except AuthError:
        return {"status": "ok"}

    user = await get_user_by_email(email_normalized)
    if user is None or user.get("status") != "active":
        # Generic response regardless of account existence
        return {"status": "ok"}

    # Issue reset token (invalidates any existing unused tokens)
    try:
        raw_token = await create_password_reset_token(user["_id"])
        await dispatch_password_reset_email(email_normalized, raw_token)
    except Exception:
        # Dispatch failure must not reveal anything
        print("[auth] password reset dispatch failed")

    return {"status": "ok"}


@router.post("/auth/reset-password")
async def reset_password(payload: ResetPasswordRequest):
    """Validate reset token and update password.

    On success, all existing sessions are revoked.
    """
    try:
        validate_password_strength(payload.password)
    except AuthError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    user_id = await consume_password_reset_token(payload.token)
    if user_id is None:
        return JSONResponse(status_code=400, content=_RESET_ERROR)

    success = await update_user_password(user_id, hash_password(payload.password))
    if not success:
        return JSONResponse(status_code=400, content=_RESET_ERROR)

    return {"status": "ok", "password_reset": True}


@router.post("/auth/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    """Change password for authenticated user.

    Requires current password. On success, revokes other sessions.
    """
    user = await get_user_by_email(current_user["email"])
    if not user or not verify_password(payload.current_password, user["password_hash"]):
        return JSONResponse(status_code=401, content={"error": "Current password is incorrect"})

    try:
        validate_password_strength(payload.new_password)
    except AuthError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    if payload.current_password == payload.new_password:
        return JSONResponse(status_code=400, content={"error": "New password must be different from current password"})

    success = await update_user_password(current_user["_id"], hash_password(payload.new_password))
    if not success:
        return JSONResponse(status_code=500, content={"error": "Could not update password"})

    return {"status": "ok", "password_changed": True}


@router.post("/auth/change-email")
async def change_email(
    payload: ChangeEmailRequest,
    current_user: dict = Depends(get_current_user),
):
    """Change email for authenticated user.

    Requires current password. On success, marks new email as unverified
    and sends verification email. Other sessions are NOT revoked (user stays logged in).
    """
    try:
        new_email_normalized = normalize_email(payload.new_email)
    except AuthError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    try:
        validate_password_strength(payload.current_password)
    except AuthError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    result = await change_user_email(current_user["_id"], payload.current_password, new_email_normalized)
    if result.get("status") == "error":
        return JSONResponse(status_code=400, content={"error": result["error"]})

    return result


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
