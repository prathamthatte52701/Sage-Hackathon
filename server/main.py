from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from routers import explain, projects, review
from services.rate_limit import check_rate_limit

app = FastAPI(title="AI Code Reviewer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        client_ip = request.client.host if request.client else "unknown"
        if not check_rate_limit(client_ip):
            return JSONResponse(
                status_code=429, content={"error": "Too many requests, please slow down"}
            )
    return await call_next(request)


app.include_router(review.router, prefix="/api")
app.include_router(explain.router, prefix="/api")
app.include_router(projects.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
