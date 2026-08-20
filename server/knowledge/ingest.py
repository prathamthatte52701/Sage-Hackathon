import asyncio

from config import EMBEDDING_MODEL, KNOWLEDGE_COLLECTION
from db.mongo import db
from knowledge.embeddings import embed_text
from knowledge.seed_data import KNOWLEDGE_RECORDS


async def ingest() -> dict:
    if db is None:
        raise RuntimeError("MONGO_URL must be configured before ingesting knowledge")

    collection = db[KNOWLEDGE_COLLECTION]
    await collection.create_index([("rule_id", 1), ("version", 1)], unique=True)
    # Mongo can't index two array fields together ("parallel arrays"), and
    # both language and framework are arrays -- split into separate indexes.
    await collection.create_index([("category", 1), ("language", 1), ("severity", 1)])
    await collection.create_index([("framework", 1)])

    upserted = 0
    matched = 0
    for record in KNOWLEDGE_RECORDS:
        vector = await embed_text(record.normalized_content())
        doc = record.with_ingestion_metadata(vector, EMBEDDING_MODEL)
        created_at = doc.pop("created_at")
        result = await collection.update_one(
            {"rule_id": record.rule_id, "version": record.version},
            {"$set": doc, "$setOnInsert": {"created_at": created_at}},
            upsert=True,
        )
        upserted += 1 if result.upserted_id else 0
        matched += result.matched_count

    return {"collection": KNOWLEDGE_COLLECTION, "records": len(KNOWLEDGE_RECORDS), "upserted": upserted, "matched": matched}


def main() -> None:
    # db/mongo.py binds AsyncIOMotorClient to the event loop active at import
    # time; asyncio.run() would spin up a *new* loop and crash with a
    # cross-loop Future error. Reuse the loop the module already bound to.
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(ingest())
    print(result)


if __name__ == "__main__":
    main()
