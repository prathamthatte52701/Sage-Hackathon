from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import AUTH_ENABLED, CORS_ORIGINS, SESSION_SECRET, MONGO_URL
from routers import auth, explain, projects, review
from services.rate_limit import check_rate_limit

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if AUTH_ENABLED and not SESSION_SECRET:
        raise RuntimeError(
            "SESSION_SECRET (or JWT_SECRET fallback) is not set. "
            "Configure it in the environment before starting the server with authentication enabled."
        )
    if MONGO_URL:
        from db.mongo import ensure_indexes

        await ensure_indexes()
    yield
    from services.groq_client import close_groq_client

    await close_groq_client()


app = FastAPI(title="AI Code Reviewer", lifespan=lifespan)

# allow_credentials=True is required for the HttpOnly session cookie to be
# sent cross-origin (client on :5173, server on :8000 in dev) -- which is
# exactly why allow_origins can no longer be "*" (the two are mutually
# exclusive per the CORS spec; browsers reject a wildcard-origin response
# that also carries Access-Control-Allow-Credentials).
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'"
    return response


# Login/signup get a tighter limit -- credential-stuffing/enumeration
# targets, and cheap enough to hammer that the default 30/min is too loose.
_AUTH_MAX_REQUESTS = 8
_AUTH_WINDOW_SECONDS = 60


# The frontend polls this endpoint on a fixed 1s interval while an analysis
# runs (up to 120 times for a single analyze/reanalyze call) -- it's a
# read-only, ownership-checked status lookup, not an action, so throttling
# it alongside everything else blocks nothing an attacker gains from and
# was exhausting the shared 30/60s IP budget on every analysis over ~25s,
# turning normal usage into random 429s on whatever request came next.
_RATE_LIMIT_EXEMPT_PREFIXES = ("/api/analysis-jobs/",)
# Same reasoning, same fix, for Fix All's own progress poll -- the project_id
# is embedded mid-path so this is a suffix check instead of a prefix one.
_RATE_LIMIT_EXEMPT_SUFFIXES = (
    "/fix-all/status",
    # V2_AUTOMATION_DISABLED:
    # Automation is intentionally excluded from CODE MASTER AI V1.
    # Preserve this code for the V2 automation workflow.
    # "/automation/status",
    "/commit-guard/status",
)


def _is_rate_limit_exempt_status_path(path: str) -> bool:
    return (
        path.startswith(_RATE_LIMIT_EXEMPT_PREFIXES)
        or path.endswith(_RATE_LIMIT_EXEMPT_SUFFIXES)
        or ("/pr-guard/" in path and path.endswith("/status"))
    )


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    exempt = _is_rate_limit_exempt_status_path(path)
    if path.startswith("/api/") and not exempt:
        client_ip = request.client.host if request.client else "unknown"
        # Credential/account-mutation endpoints get a tight bucket to blunt
        # enumeration and credential stuffing. All share one bucket per IP so
        # an attacker hammering any of them is throttled globally.
        if path in (
            "/api/auth/login",
            "/api/auth/signup",
            "/api/auth/verify-email",
            "/api/auth/resend-verification",
        ):
            allowed = check_rate_limit(f"auth:{client_ip}", _AUTH_MAX_REQUESTS, _AUTH_WINDOW_SECONDS)
        else:
            allowed = check_rate_limit(client_ip)
        if not allowed:
            return JSONResponse(
                status_code=429, content={"error": "Too many requests, please slow down"}
            )
    return await call_next(request)


# Basic CSRF/origin defence for cookie-authenticated, state-changing requests.
# The session cookie is SameSite=Lax (blocks cross-site script/iframe POSTs),
# and this middleware additionally rejects cross-origin mutations whose Origin
# is not an explicitly allowed CORS origin. Same-origin (no Origin header) and
# non-mutating requests are unaffected, so the legitimate SPA is never blocked.
@app.middleware("http")
async def csrf_origin_middleware(request: Request, call_next):
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)
    origin = request.headers.get("origin")
    if not origin:
        # Non-browser / same-origin request without an Origin header.
        return await call_next(request)
    from urllib.parse import urlparse

    allowed_hosts = {urlparse(o).netloc for o in CORS_ORIGINS}
    if urlparse(origin).netloc not in allowed_hosts:
        return JSONResponse(status_code=403, content={"error": "Cross-origin request blocked"})
    return await call_next(request)


if AUTH_ENABLED:
    app.include_router(auth.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(explain.router, prefix="/api")
app.include_router(projects.router, prefix="/api")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": "Invalid request", "detail": exc.errors()})


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    print(f"[api] unhandled error on {request.url.path}: {type(exc).__name__}")
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.get("/health")
async def health():
    return {"status": "ok", "service": "code-master-ai"}


@app.get("/health/live")
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready():
    if not MONGO_URL:
        return JSONResponse(status_code=503, content={"status": "not_ready", "dependency": "mongo"})
    try:
        from db.mongo import get_db

        database = get_db()
        await database.command("ping")
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "dependency": "mongo"})
    return {"status": "ready"}
