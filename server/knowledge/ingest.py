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
    await collection.create_index([("category", 1), ("language", 1), ("framework", 1), ("severity", 1)])

    upserted = 0
    matched = 0
    for record in KNOWLEDGE_RECORDS:
        vector = await embed_text(record.normalized_content())
        doc = record.with_ingestion_metadata(vector, EMBEDDING_MODEL)
        result = await collection.update_one(
            {"rule_id": record.rule_id, "version": record.version},
            {"$set": doc, "$setOnInsert": {"created_at": doc["created_at"]}},
            upsert=True,
        )
        upserted += 1 if result.upserted_id else 0
        matched += result.matched_count

    return {"collection": KNOWLEDGE_COLLECTION, "records": len(KNOWLEDGE_RECORDS), "upserted": upserted, "matched": matched}


def main() -> None:
    result = asyncio.run(ingest())
    print(result)


if __name__ == "__main__":
    main()
