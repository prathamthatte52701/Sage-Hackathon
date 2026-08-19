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


async def save_project(project: dict, session_id: str) -> str:
    doc = {**project, "session_id": session_id, "created_at": datetime.now(timezone.utc)}
    result = await db.projects.insert_one(doc)
    return str(result.inserted_id)


async def get_project(project_id: str):
    from bson import ObjectId

    doc = await db.projects.find_one({"_id": ObjectId(project_id)})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def update_project(project_id: str, updates: dict):
    from bson import ObjectId

    await db.projects.update_one({"_id": ObjectId(project_id)}, {"$set": updates})
