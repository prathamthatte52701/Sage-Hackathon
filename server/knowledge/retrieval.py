from config import KNOWLEDGE_COLLECTION, KNOWLEDGE_VECTOR_INDEX
from db.mongo import db
from knowledge.embeddings import EmbeddingConfigurationError, EmbeddingProviderError, embed_text
from knowledge.seed_data import KNOWLEDGE_RECORDS


class KnowledgeRetrievalUnavailable(RuntimeError):
    pass


def _metadata_filter(language: str | None, frameworks: list[str] | None, category: str | None) -> dict:
    clauses = []
    if language:
        clauses.append({"language": {"$in": [language.lower(), "any"]}})
    if frameworks:
        clauses.append({"framework": {"$in": [f.lower() for f in frameworks] + ["any"]}})
    if category:
        clauses.append({"category": category})
    return {"$and": clauses} if clauses else {}


async def retrieve_knowledge(
    query: str,
    language: str | None = None,
    frameworks: list[str] | None = None,
    category: str | None = None,
    top_k: int = 4,
) -> dict:
    if db is None:
        return _fallback_records(language, frameworks, category, top_k, "mongodb_unavailable")

    try:
        vector = await embed_text(query)
        pipeline = [
            {
                "$vectorSearch": {
                    "index": KNOWLEDGE_VECTOR_INDEX,
                    "path": "embedding",
                    "queryVector": vector,
                    "numCandidates": max(20, top_k * 10),
                    "limit": top_k,
                    "filter": _metadata_filter(language, frameworks, category),
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "rule_id": 1,
                    "title": 1,
                    "category": 1,
                    "subcategory": 1,
                    "language": 1,
                    "framework": 1,
                    "severity": 1,
                    "description": 1,
                    "why_it_matters": 1,
                    "exceptions": 1,
                    "fix_strategy": 1,
                    "standards": 1,
                    "source_urls": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        docs = await db[KNOWLEDGE_COLLECTION].aggregate(pipeline).to_list(length=top_k)
        return {"mode": "vector", "available": True, "records": docs}
    except (EmbeddingConfigurationError, EmbeddingProviderError, Exception) as exc:
        return _fallback_records(language, frameworks, category, top_k, f"vector_unavailable:{type(exc).__name__}")


def _fallback_records(language: str | None, frameworks: list[str] | None, category: str | None, top_k: int, reason: str) -> dict:
    language = (language or "").lower()
    framework_set = {f.lower() for f in frameworks or []}
    records = []
    for record in KNOWLEDGE_RECORDS:
        if category and record.category != category:
            continue
        if language and "any" not in record.language and language not in record.language:
            continue
        if framework_set and "any" not in record.framework and not (framework_set & set(record.framework)):
            continue
        doc = record.model_dump(exclude={"embedding"})
        doc["score"] = None
        records.append(doc)
    return {"mode": "deterministic_fallback", "available": False, "reason": reason, "records": records[:top_k]}
