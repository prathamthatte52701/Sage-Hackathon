from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from pymongo.errors import DuplicateKeyError

from config import COOKIE_SECURE, JWT_EXPIRE_MINUTES
from db.mongo import create_user, get_user_by_email
from models.schemas import LoginRequest, SignupRequest, UserOut
from services.auth import (
    COOKIE_NAME,
    AuthError,
    create_session_token,
    get_current_user,
    hash_password,
    normalize_email,
    validate_password_strength,
    verify_password,
)

# AUTH DISABLED: entire router commented out, not registered in main.py.
# Uncomment this and the include_router(auth.router, ...) line in main.py
# to bring signup/login/logout/me back.

# router = APIRouter()
#
# _GENERIC_AUTH_ERROR = {"error": "Invalid email or password"}
# _SIGNUP_ERROR = {"error": "Could not create account, please try again"}
#
#
# def _user_out(user: dict) -> dict:
#     created_at = user.get("created_at")
#     return {
#         "id": user["_id"],
#         "email": user["email"],
#         "created_at": created_at.isoformat() if created_at else "",
#     }
#
#
# def _set_session_cookie(response: Response, token: str) -> None:
#     response.set_cookie(
#         key=COOKIE_NAME,
#         value=token,
#         httponly=True,
#         secure=COOKIE_SECURE,
#         samesite="lax",
#         max_age=JWT_EXPIRE_MINUTES * 60,
#         path="/",
#     )
#
#
# @router.post("/auth/signup", response_model=UserOut)
# async def signup(payload: SignupRequest, response: Response):
#     try:
#         email = normalize_email(payload.email)
#         validate_password_strength(payload.password)
#     except AuthError as exc:
#         return JSONResponse(status_code=400, content={"error": str(exc)})
#
#     try:
#         user_id = await create_user(email, hash_password(payload.password))
#     except DuplicateKeyError:
#         # Same generic shape as an invalid-input 400 -- never confirm an email
#         # already has an account via a distinct error message.
#         return JSONResponse(status_code=400, content={"error": "Could not create account, please try again"})
#     except Exception as exc:
#         print(f"[auth] signup error: {type(exc).__name__}")
#         return JSONResponse(status_code=500, content=_SIGNUP_ERROR)
#
#     token = create_session_token(user_id)
#     _set_session_cookie(response, token)
#     user = await get_user_by_email(email)
#     print(f"[auth] signup user_id={user_id}")
#     return _user_out(user)
#
#
# @router.post("/auth/login", response_model=UserOut)
# async def login(payload: LoginRequest, response: Response):
#     try:
#         email = normalize_email(payload.email)
#     except AuthError:
#         return JSONResponse(status_code=401, content=_GENERIC_AUTH_ERROR)
#
#     user = await get_user_by_email(email)
#     if user is None or not verify_password(payload.password, user["password_hash"]):
#         # Deliberately identical response whether the email doesn't exist or
#         # the password is wrong -- never reveal which one it was. Safe to log
#         # the distinction server-side though (email is not a secret).
#         print(f"[auth] login failed email={email} reason={'unknown_account' if user is None else 'bad_password'}")
#         return JSONResponse(status_code=401, content=_GENERIC_AUTH_ERROR)
#
#     token = create_session_token(user["_id"])
#     _set_session_cookie(response, token)
#     print(f"[auth] login success user_id={user['_id']}")
#     return _user_out(user)
#
#
# @router.post("/auth/logout")
# async def logout(response: Response):
#     response.delete_cookie(COOKIE_NAME, path="/")
#     print("[auth] logout")
#     return {"status": "ok"}
#
#
# @router.get("/auth/me", response_model=UserOut)
# async def me(current_user: dict = Depends(get_current_user)):
#     return _user_out(current_user)
