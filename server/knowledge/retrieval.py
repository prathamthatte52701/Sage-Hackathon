import re

from pydantic import BaseModel

from config import KNOWLEDGE_COLLECTION, KNOWLEDGE_VECTOR_INDEX
from db.mongo import get_db
from knowledge.embeddings import EmbeddingConfigurationError, EmbeddingProviderError, embed_text
from knowledge.seed_data import KNOWLEDGE_RECORDS


class KnowledgeRetrievalUnavailable(RuntimeError):
    pass


class InternalKnowledgeResult(BaseModel):
    knowledge_id: str
    rule_id: str | None = None
    title: str
    content: str = ""
    retrieval_method: str
    relevance_score: float | None = None
    relevance_reason: str = ""
    record: dict


_WORD_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{2,}")
_SECRETISH_RE = re.compile(
    r"(?i)(password|secret|api[_-]?key|token)\s*=\s*['\"][^'\"]+['\"]"
)


def redact_sensitive_query_text(text: str, max_chars: int = 1200) -> str:
    redacted = _SECRETISH_RE.sub(r"\1 = \"[REDACTED]\"", text or "")
    return redacted[:max_chars]


def build_finding_knowledge_query(
    finding: dict,
    surrounding_context: str = "",
    detector_name: str | None = None,
) -> str:
    parts = [
        f"RULE: {finding.get('rule', '')}",
        f"DETECTOR: {detector_name or finding.get('rule', '')}",
        f"EVIDENCE: {finding.get('evidence', '')}",
        f"REASON / FINDING: {finding.get('message', '')}",
    ]
    if surrounding_context:
        parts.append(f"SURROUNDING CONTEXT: {surrounding_context[:700]}")
    return redact_sensitive_query_text("\n".join(part for part in parts if part.strip()))


def _metadata_filter(language: str | None, frameworks: list[str] | None, category: str | None) -> dict:
    clauses = []
    if language:
        clauses.append({"language": {"$in": [language.lower(), "any"]}})
    if frameworks:
        clauses.append({"framework": {"$in": [f.lower() for f in frameworks] + ["any"]}})
    if category:
        clauses.append({"category": category})
    return {"$and": clauses} if clauses else {}


def _tokens(text: str) -> set[str]:
    tokens = set()
    for token in _WORD_RE.findall(text or ""):
        lowered = token.lower()
        tokens.add(lowered[:-1] if len(lowered) > 4 and lowered.endswith("s") else lowered)
    return tokens


def _record_matches_metadata(record, language: str, framework_set: set[str], category: str | None) -> bool:
    if category and record.category != category:
        return False
    if language and "any" not in record.language and language not in record.language:
        return False
    if framework_set and "any" not in record.framework and not (framework_set & set(record.framework)):
        return False
    return True


def _record_to_doc(record, retrieval_method: str, score: float | None = None, reason: str = "") -> dict:
    doc = record.model_dump(exclude={"embedding"})
    doc["knowledge_id"] = record.rule_id
    doc["retrieval_method"] = retrieval_method
    doc["relevance_score"] = score
    doc["relevance_reason"] = reason
    doc["score"] = score
    return doc


def _normalize_semantic_doc(doc: dict) -> dict:
    normalized = dict(doc)
    knowledge_id = normalized.get("knowledge_id") or normalized.get("rule_id") or str(normalized.get("_id", ""))
    normalized["knowledge_id"] = str(knowledge_id)
    normalized["retrieval_method"] = "semantic"
    normalized["relevance_score"] = normalized.get("score")
    normalized["relevance_reason"] = "Atlas Vector Search semantic match"
    normalized.pop("_id", None)
    return normalized


def _exact_records(
    query: str,
    language: str | None,
    frameworks: list[str] | None,
    category: str | None,
    exact_rule_id: str | None = None,
) -> list[dict]:
    language = (language or "").lower()
    framework_set = {f.lower() for f in frameworks or []}
    query_lower = (query or "").lower()
    query_tokens = _tokens(query_lower)
    exact = []

    for record in KNOWLEDGE_RECORDS:
        if not _record_matches_metadata(record, language, framework_set, category):
            continue

        reason = ""
        if exact_rule_id and record.rule_id.lower() == exact_rule_id.lower():
            reason = "explicit rule_id match"
        else:
            searchable = " ".join(
                [
                    record.rule_id,
                    record.title,
                    record.description,
                    " ".join(record.bad_patterns),
                    " ".join(record.detection_hints),
                    record.content,
                ]
            ).lower()
            title_tokens = _tokens(record.title)
            hint_tokens = _tokens(" ".join(record.detection_hints + record.bad_patterns + [record.description]))
            phrase_hit = bool(record.title and record.title.lower() in query_lower)
            strong_overlap = len(query_tokens & (title_tokens | hint_tokens)) >= 2
            if phrase_hit or strong_overlap:
                reason = "deterministic title/pattern match"

        if reason:
            exact.append(_record_to_doc(record, "exact_rule", 1.0, reason))

    return exact


def _fallback_records(
    language: str | None,
    frameworks: list[str] | None,
    category: str | None,
    top_k: int,
    reason: str,
    exact: list[dict] | None = None,
) -> dict:
    records = list(exact or [])
    language = (language or "").lower()
    framework_set = {f.lower() for f in frameworks or []}
    seen = {r.get("knowledge_id") or r.get("rule_id") for r in records}
    for record in KNOWLEDGE_RECORDS:
        if not _record_matches_metadata(record, language, framework_set, category):
            continue
        if record.rule_id in seen:
            continue
        doc = _record_to_doc(record, "deterministic_fallback", None, reason)
        records.append(doc)
        seen.add(record.rule_id)
        if len(records) >= top_k:
            break
    return {"mode": "deterministic_fallback", "available": False, "reason": reason, "records": records[:top_k]}


def _merge_results(exact: list[dict], semantic: list[dict], top_k: int) -> list[dict]:
    merged = []
    seen = set()
    for doc in exact + semantic:
        key = doc.get("knowledge_id") or doc.get("rule_id") or doc.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(doc)
        if len(merged) >= top_k:
            break
    return merged


async def retrieve_knowledge(
    query: str,
    language: str | None = None,
    frameworks: list[str] | None = None,
    category: str | None = None,
    top_k: int = 4,
    exact_rule_id: str | None = None,
) -> dict:
    exact = _exact_records(query, language, frameworks, category, exact_rule_id)
    db = get_db()
    if db is None:
        return _fallback_records(language, frameworks, category, top_k, "mongodb_unavailable", exact)

    try:
        vector = await embed_text(query)
        pipeline = [
            {
                "$vectorSearch": {
                    "index": KNOWLEDGE_VECTOR_INDEX,
                    "path": "embedding",
                    "queryVector": vector,
                    "numCandidates": max(20, top_k * 10),
                    "limit": max(top_k, 8),
                    "filter": _metadata_filter(language, frameworks, category),
                }
            },
            {
                "$project": {
                    "_id": 1,
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
        docs = await db[KNOWLEDGE_COLLECTION].aggregate(pipeline).to_list(length=max(top_k, 8))
        semantic = [_normalize_semantic_doc(doc) for doc in docs]
        records = _merge_results(exact, semantic, top_k)
        method_ids = [r.get("knowledge_id") or r.get("rule_id") for r in records]
        print(
            f"[knowledge] mode=hybrid exact={len(exact)} semantic={len(semantic)} "
            f"top={method_ids} scores={[round(r.get('score'), 3) for r in records if isinstance(r.get('score'), (int, float))]}"
        )
        return {"mode": "hybrid", "available": True, "records": records}
    except (EmbeddingConfigurationError, EmbeddingProviderError, Exception) as exc:
        return _fallback_records(language, frameworks, category, top_k, f"vector_unavailable:{type(exc).__name__}", exact)
