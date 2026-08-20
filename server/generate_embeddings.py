import asyncio

from db.mongo import db, hydrate_file_content
from services.embeddings import generate_embedding

EMBEDDING_DIMENSIONS = 384
MAX_CHARS_PER_FILE = 2000  # keep embedding input bounded for large projects


def _build_project_text(doc: dict) -> str:
    parts = []
    for f in doc.get("files", []):
        path = f.get("path")
        content = f.get("content") or ""
        if not path or not content:
            continue
        parts.append(f"# {path}\n{content[:MAX_CHARS_PER_FILE]}")
    return "\n\n".join(parts).strip()


async def main():
    if db is None:
        raise RuntimeError("MONGO_URL is not configured")

    embedded = skipped_existing = skipped_no_text = 0

    async for doc in db.projects.find({}):
        project_id = doc["_id"]

        existing = doc.get("embedding")
        if isinstance(existing, list) and len(existing) == EMBEDDING_DIMENSIONS:
            print(f"Skipped (existing embedding): {project_id}")
            skipped_existing += 1
            continue

        files = doc.get("files", [])
        await hydrate_file_content(files)
        text = _build_project_text(doc)

        if not text:
            print(f"Skipped (no meaningful text): {project_id}")
            skipped_no_text += 1
            continue

        embedding = generate_embedding(text)
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise RuntimeError(f"Expected {EMBEDDING_DIMENSIONS} dimensions, got {len(embedding)}")
        await db.projects.update_one({"_id": project_id}, {"$set": {"embedding": embedding}})
        print(f"Embedded: {project_id} ({len(embedding)} dimensions, {len(files)} files)")
        embedded += 1

    print(f"\nDone. embedded={embedded} skipped_existing={skipped_existing} skipped_no_text={skipped_no_text}")


if __name__ == "__main__":
    # db/mongo.py binds AsyncIOMotorClient to the event loop active at import
    # time; asyncio.run() spins up a *new* loop and crashes with a
    # cross-loop Future error. Reuse the loop the module already bound to.
    asyncio.get_event_loop().run_until_complete(main())
