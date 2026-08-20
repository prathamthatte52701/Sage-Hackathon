import pytest

from knowledge.embeddings import EmbeddingConfigurationError, embed_text
from knowledge.retrieval import retrieve_knowledge
from knowledge.schema import KnowledgeRecord


def test_knowledge_schema_generates_normalized_content():
    record = KnowledgeRecord(
        rule_id="TEST-1",
        title="Validate input",
        category="api_design",
        description="Validate request data",
        why_it_matters="Prevents malformed input",
        fix_strategy="Use schema validation",
        production_impact="Improves reliability",
        content="Boundary validation",
    )
    assert "Validate input" in record.normalized_content()
    assert record.language == ["any"]


@pytest.mark.asyncio
async def test_embedding_fails_clearly_without_provider():
    with pytest.raises(EmbeddingConfigurationError):
        await embed_text("hello")


@pytest.mark.asyncio
async def test_retrieval_falls_back_when_vector_unavailable():
    result = await retrieve_knowledge("hardcoded secret", language="python", category="security")
    assert result["mode"] == "deterministic_fallback"
    assert result["available"] is False
    assert result["records"]
