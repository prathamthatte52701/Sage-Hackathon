import asyncio
import copy
from datetime import datetime, timezone

import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

from config import MONGO_DB_NAME, MONGO_URL

_client = None
db = None
fs_bucket = None


def _ensure_client() -> None:
    """Lazily construct the Motor client on first real use, inside whatever
    event loop is actually running at that moment.

    Constructing AsyncIOMotorClient eagerly at module-import time binds its
    background connection/topology monitoring to whatever loop happens to be
    "current" then. Under a plain script that's harmless (the script's own
    asyncio.get_event_loop().run_until_complete() reuses that same implicit
    loop). Under uvicorn it isn't: main.py (and therefore this module) is
    imported before uvicorn's real serving loop is created via asyncio.run(),
    so the client binds to a throwaway loop that gets discarded — every
    subsequent operation then fails with "Future ... attached to a different
    loop". Deferring construction to first use means it always binds to
    whichever loop is genuinely running the call.
    """
    global _client, db, fs_bucket
    if _client is not None or not MONGO_URL:
        return
    _client = AsyncIOMotorClient(MONGO_URL, tlsCAFile=certifi.where())
    db = _client[MONGO_DB_NAME]
    fs_bucket = AsyncIOMotorGridFSBucket(db)


def get_db():
    """Public accessor for callers outside this module. Prefer this over
    `from db.mongo import db`, which would capture whatever `db` was at
    import time (likely still None) rather than the lazily-constructed value."""
    _ensure_client()
    return db


def _require_db():
    _ensure_client()
    if db is None:
        raise RuntimeError("MONGO_URL is not configured")
    return db


def _require_fs_bucket():
    _ensure_client()
    if fs_bucket is None:
        raise RuntimeError("MONGO_URL is not configured")
    return fs_bucket


async def save_review(code: str, language: str, issues: list, summary: str, session_id: str):
    database = _require_db()
    doc = {
        "code_snippet": code,
        "language": language,
        "issues": issues,
        "summary": summary,
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc),
    }
    await database.reviews.insert_one(doc)


async def get_history(session_id: str):
    database = _require_db()
    cursor = database.reviews.find({"session_id": session_id}).sort("created_at", -1).limit(20)
    results = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        results.append(doc)
    return results


async def store_file_content(content: str, project_id_hint: str = "") -> str:
    """Stores file content in GridFS, returns the GridFS file id as a string."""
    bucket = _require_fs_bucket()
    file_id = await bucket.upload_from_stream(
        f"{project_id_hint}-chunk",
        content.encode("utf-8"),
    )
    return str(file_id)


async def fetch_file_content(content_ref: str) -> str:
    """Fetches previously stored content by its GridFS id string."""
    from bson import ObjectId

    bucket = _require_fs_bucket()
    stream = await bucket.open_download_stream(ObjectId(content_ref))
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
    database = _require_db()
    project_copy = copy.deepcopy(project)  # don't mutate caller's dict
    await _replace_content_with_refs(project_copy.get("files", []))
    doc = {**project_copy, "session_id": session_id, "created_at": datetime.now(timezone.utc)}
    result = await database.projects.insert_one(doc)
    return str(result.inserted_id)


async def get_project(project_id: str):
    from bson.errors import InvalidId
    from bson import ObjectId

    database = _require_db()
    try:
        object_id = ObjectId(project_id)
    except InvalidId:
        return None

    doc = await database.projects.find_one({"_id": object_id})
    if doc:
        doc["_id"] = str(doc["_id"])
        await hydrate_file_content(doc.get("files", []))
    return doc


async def update_project(project_id: str, updates: dict):
    from bson.errors import InvalidId
    from bson import ObjectId

    database = _require_db()
    if "files" in updates:
        updates = dict(updates)
        updates["files"] = copy.deepcopy(updates["files"])
        await _replace_content_with_refs(updates["files"], project_id)

    try:
        object_id = ObjectId(project_id)
    except InvalidId:
        return

    await database.projects.update_one({"_id": object_id}, {"$set": updates})
