from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import AUTH_ENABLED, CORS_ORIGINS, JWT_SECRET, MONGO_URL
from routers import auth, explain, projects, review
from services.rate_limit import check_rate_limit

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if AUTH_ENABLED and not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not set. Configure it in the environment before starting the server.")
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


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        client_ip = request.client.host if request.client else "unknown"
        if request.url.path in ("/api/auth/login", "/api/auth/signup"):
            allowed = check_rate_limit(f"auth:{client_ip}", _AUTH_MAX_REQUESTS, _AUTH_WINDOW_SECONDS)
        else:
            allowed = check_rate_limit(client_ip)
        if not allowed:
            return JSONResponse(
                status_code=429, content={"error": "Too many requests, please slow down"}
            )
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
    return {"status": "ok", "service": "sage"}


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
