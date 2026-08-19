from datetime import datetime, timezone

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

from config import MONGO_DB_NAME, MONGO_URL

_client = AsyncIOMotorClient(MONGO_URL, tlsCAFile=certifi.where()) if MONGO_URL else None
db = _client[MONGO_DB_NAME] if _client else None


async def save_review(code: str, language: str, issues: list, summary: str, session_id: str):
    doc = {
        "code_snippet": code,
        "language": language,
        "issues": issues,
        "summary": summary,
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc),
    }
    await db.reviews.insert_one(doc)


async def get_history(session_id: str):
    cursor = db.reviews.find({"session_id": session_id}).sort("created_at", -1).limit(20)
    results = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        results.append(doc)
    return results
