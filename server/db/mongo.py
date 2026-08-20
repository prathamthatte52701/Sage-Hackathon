import asyncio
import copy
from datetime import datetime, timezone

import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

from config import MONGO_DB_NAME, MONGO_URL

_client = AsyncIOMotorClient(MONGO_URL, tlsCAFile=certifi.where()) if MONGO_URL else None
db = _client[MONGO_DB_NAME] if _client else None
fs_bucket = AsyncIOMotorGridFSBucket(db) if db is not None else None


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


async def store_file_content(content: str, project_id_hint: str = "") -> str:
    """Stores file content in GridFS, returns the GridFS file id as a string."""
    file_id = await fs_bucket.upload_from_stream(
        f"{project_id_hint}-chunk",
        content.encode("utf-8"),
    )
    return str(file_id)


async def fetch_file_content(content_ref: str) -> str:
    """Fetches previously stored content by its GridFS id string."""
    from bson import ObjectId

    stream = await fs_bucket.open_download_stream(ObjectId(content_ref))
    data = await stream.read()
    return data.decode("utf-8")


async def hydrate_file_content(files: list[dict]) -> None:
    """Fetches every listed file's content from GridFS concurrently and sets
    it back onto each entry's "content" key, in place - one batched round
    trip instead of one-at-a-time, since a sequential per-file fetch is the
    real cost at project sizes in the thousands of files. Callers that don't
    need file text (e.g. scoring, which only reads findings/tests/configs)
    should skip calling this entirely - it's not free.
    """
    targets = [f for f in files if f.get("content_ref")]
    if not targets:
        return
    contents = await asyncio.gather(*(fetch_file_content(f["content_ref"]) for f in targets))
    for file_entry, content in zip(targets, contents):
        file_entry["content"] = content


async def _replace_content_with_refs(files: list[dict], project_id_hint: str = "") -> None:
    """In place: for every file entry carrying inline "content", store it in
    GridFS and swap "content" for "content_ref" - never leaves both keys
    holding the same data, so the persisted document never embeds full file
    text (the thing that blew past Mongo's 16MB document limit)."""
    for file_entry in files:
        content = file_entry.get("content")
        if content is not None:
            hint = project_id_hint or file_entry.get("path", "file")
            file_entry["content_ref"] = await store_file_content(content, hint)
            del file_entry["content"]


async def save_project(project: dict, session_id: str) -> str:
    project_copy = copy.deepcopy(project)  # don't mutate caller's dict
    await _replace_content_with_refs(project_copy.get("files", []))
    doc = {**project_copy, "session_id": session_id, "created_at": datetime.now(timezone.utc)}
    result = await db.projects.insert_one(doc)
    return str(result.inserted_id)


async def get_project(project_id: str):
    from bson import ObjectId

    doc = await db.projects.find_one({"_id": ObjectId(project_id)})
    if doc:
        doc["_id"] = str(doc["_id"])
        await hydrate_file_content(doc.get("files", []))
    return doc


async def update_project(project_id: str, updates: dict):
    from bson import ObjectId

    if "files" in updates:
        updates = dict(updates)
        updates["files"] = copy.deepcopy(updates["files"])
        await _replace_content_with_refs(updates["files"], project_id)

    await db.projects.update_one({"_id": ObjectId(project_id)}, {"$set": updates})
