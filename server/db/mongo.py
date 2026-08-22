import asyncio
import copy
from hashlib import sha256
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


async def save_review(code: str, language: str, issues: list, summary: str, owner_user_id: str):
    database = _require_db()
    doc = {
        "code_snippet": code,
        "language": language,
        "issues": issues,
        "summary": summary,
        "owner_user_id": owner_user_id,
        "created_at": datetime.now(timezone.utc),
    }
    await database.reviews.insert_one(doc)


async def get_history(owner_user_id: str):
    database = _require_db()
    cursor = database.reviews.find({"owner_user_id": owner_user_id}).sort("created_at", -1).limit(20)
    results = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        results.append(doc)
    return results


def _content_hash(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


async def store_file_content(content: str, project_id_hint: str = "") -> str:
    """Stores file content in GridFS, returns the GridFS file id as a string."""
    bucket = _require_fs_bucket()
    file_id = await bucket.upload_from_stream(
        f"{project_id_hint}-chunk",
        content.encode("utf-8"),
    )
    return str(file_id)


async def store_binary_content(content: bytes, project_id_hint: str = "") -> str:
    file_id = await _require_fs_bucket().upload_from_stream(f"{project_id_hint}-asset", content)
    return str(file_id)


async def fetch_file_content(content_ref: str) -> str:
    """Fetches previously stored content by its GridFS id string."""
    from bson import ObjectId

    bucket = _require_fs_bucket()
    stream = await bucket.open_download_stream(ObjectId(content_ref))
    data = await stream.read()
    return data.decode("utf-8")


async def fetch_binary_content(content_ref: str) -> bytes:
    from bson import ObjectId

    stream = await _require_fs_bucket().open_download_stream(ObjectId(content_ref))
    return await stream.read()


async def delete_file_content(content_ref: str) -> None:
    from bson import ObjectId

    await _require_fs_bucket().delete(ObjectId(content_ref))


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


async def _replace_content_with_refs(files: list[dict], project_id_hint: str = "") -> list[str]:
    """In place: for every file entry carrying inline "content", store it in
    GridFS and swap "content" for "content_ref" - never leaves both keys
    holding the same data, so the persisted document never embeds full file
    text (the thing that blew past Mongo's 16MB document limit)."""
    replaced_refs = []
    for file_entry in files:
        binary_content = file_entry.pop("binary_content", None)
        if binary_content is not None:
            old_ref = file_entry.get("binary_ref")
            file_entry["binary_ref"] = await store_binary_content(binary_content, project_id_hint or file_entry.get("path", "asset"))
            if old_ref:
                replaced_refs.append(old_ref)
        content = file_entry.get("content")
        if content is not None:
            digest = _content_hash(content)
            # A hydrated but unchanged file should keep its existing GridFS
            # object. This prevents a one-file patch from rewriting a whole
            # project and keeps the document compact after every update.
            if file_entry.get("content_ref") and file_entry.get("content_hash") == digest:
                del file_entry["content"]
                continue
            hint = project_id_hint or file_entry.get("path", "file")
            old_ref = file_entry.get("content_ref")
            file_entry["content_ref"] = await store_file_content(content, hint)
            file_entry["content_hash"] = digest
            del file_entry["content"]
            if old_ref:
                replaced_refs.append(old_ref)
    return replaced_refs


async def save_project(project: dict, session_id: str, owner_user_id: str) -> str:
    database = _require_db()
    project_copy = copy.deepcopy(project)  # don't mutate caller's dict
    await _replace_content_with_refs(project_copy.get("files", []))
    doc = {
        **project_copy,
        "session_id": session_id,
        "owner_user_id": owner_user_id,
        "created_at": datetime.now(timezone.utc),
        "source_revision": 1,
        "analysis_revision": 0,
        "analysis_status": "not_started",
    }
    result = await database.projects.insert_one(doc)
    return str(result.inserted_id)


async def get_owned_project(project_id: str, owner_user_id: str):
    """The only project fetch routers should use: id and ownership are checked
    in the same query, so there's no separate "fetch, then compare owner"
    step a route can forget. Returns None for a bad id, a missing project, OR
    someone else's project -- identical to "not found" from the caller's
    perspective, which is what keeps a 404 from leaking existence."""
    from bson.errors import InvalidId
    from bson import ObjectId

    database = _require_db()
    try:
        object_id = ObjectId(project_id)
    except InvalidId:
        return None

    doc = await database.projects.find_one({"_id": object_id, "owner_user_id": owner_user_id})
    if doc:
        doc["_id"] = str(doc["_id"])
        await hydrate_file_content(doc.get("files", []))
    return doc


async def update_owned_project(project_id: str, owner_user_id: str, updates: dict):
    from bson.errors import InvalidId
    from bson import ObjectId

    database = _require_db()
    replaced_refs = []
    if "files" in updates:
        updates = dict(updates)
        updates["files"] = copy.deepcopy(updates["files"])
        replaced_refs = await _replace_content_with_refs(updates["files"], project_id)

    try:
        object_id = ObjectId(project_id)
    except InvalidId:
        return

    result = await database.projects.update_one({"_id": object_id, "owner_user_id": owner_user_id}, {"$set": updates})
    if result.matched_count:
        for content_ref in replaced_refs:
            try:
                await delete_file_content(content_ref)
            except Exception as exc:
                # The database already points at the replacement. Keeping an
                # orphan temporarily is safer than turning a completed write
                # into a failed request; maintenance can retry cleanup later.
                print(f"[mongo] deferred old GridFS cleanup: {type(exc).__name__}")


async def create_analysis_job(project_id: str, owner_user_id: str) -> str:
    from bson import ObjectId

    database = _require_db()
    result = await database.analysis_jobs.insert_one(
        {
            "project_id": ObjectId(project_id),
            "owner_user_id": owner_user_id,
            "status": "queued",
            "created_at": datetime.now(timezone.utc),
        }
    )
    return str(result.inserted_id)


async def get_owned_analysis_job(job_id: str, owner_user_id: str):
    from bson import ObjectId
    from bson.errors import InvalidId

    try:
        object_id = ObjectId(job_id)
    except InvalidId:
        return None
    doc = await _require_db().analysis_jobs.find_one({"_id": object_id, "owner_user_id": owner_user_id})
    if doc:
        doc["_id"] = str(doc["_id"])
        doc["project_id"] = str(doc["project_id"])
    return doc


async def get_owned_project_metadata(project_id: str, owner_user_id: str):
    """Fetch project state without hydrating GridFS source bodies."""
    from bson.errors import InvalidId
    from bson import ObjectId

    try:
        object_id = ObjectId(project_id)
    except InvalidId:
        return None
    doc = await _require_db().projects.find_one({"_id": object_id, "owner_user_id": owner_user_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def get_owned_project_file(project_id: str, owner_user_id: str, path: str):
    """Return one owner-scoped file with text hydrated on demand only."""
    project = await get_owned_project_metadata(project_id, owner_user_id)
    if project is None:
        return None
    file_entry = next((entry for entry in project.get("files", []) if entry.get("path") == path), None)
    if file_entry is None:
        return None
    file_entry = copy.deepcopy(file_entry)
    if file_entry.get("content_ref"):
        file_entry["content"] = await fetch_file_content(file_entry["content_ref"])
    return file_entry


async def update_analysis_job(job_id: str, owner_user_id: str, updates: dict) -> None:
    from bson import ObjectId
    from bson.errors import InvalidId

    try:
        object_id = ObjectId(job_id)
    except InvalidId:
        return
    await _require_db().analysis_jobs.update_one(
        {"_id": object_id, "owner_user_id": owner_user_id}, {"$set": updates}
    )


async def create_user(email: str, password_hash: str) -> str:
    """Raises pymongo.errors.DuplicateKeyError if the unique email index rejects it."""
    database = _require_db()
    doc = {
        "email": email,
        "password_hash": password_hash,
        "created_at": datetime.now(timezone.utc),
    }
    result = await database.users.insert_one(doc)
    return str(result.inserted_id)


async def get_user_by_email(email: str):
    database = _require_db()
    doc = await database.users.find_one({"email": email})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def get_user_by_id(user_id: str):
    from bson.errors import InvalidId
    from bson import ObjectId

    database = _require_db()
    try:
        object_id = ObjectId(user_id)
    except InvalidId:
        return None
    doc = await database.users.find_one({"_id": object_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def ensure_indexes() -> None:
    """Called once at app startup. Safe to call repeatedly (create_index is
    idempotent on an unchanged spec)."""
    database = _require_db()
    await database.users.create_index("email", unique=True)
    await database.projects.create_index("owner_user_id")
    await database.analysis_jobs.create_index([("owner_user_id", 1), ("project_id", 1), ("status", 1)])
