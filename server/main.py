from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import explain, review

app = FastAPI(title="AI Code Reviewer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review.router, prefix="/api")
app.include_router(explain.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
