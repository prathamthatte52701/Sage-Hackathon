import httpx

from config import EMBEDDING_API_KEY, EMBEDDING_API_URL, EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, EMBEDDING_PROVIDER


class EmbeddingConfigurationError(RuntimeError):
    pass


class EmbeddingProviderError(RuntimeError):
    pass


def _validate_embedding(vector: list[float]) -> list[float]:
    if not vector or not all(isinstance(v, (int, float)) for v in vector):
        raise EmbeddingProviderError("Embedding provider returned an invalid vector")
    if EMBEDDING_DIMENSIONS and len(vector) != EMBEDDING_DIMENSIONS:
        raise EmbeddingProviderError(
            f"Embedding dimension mismatch: expected {EMBEDDING_DIMENSIONS}, got {len(vector)}"
        )
    return [float(v) for v in vector]


async def embed_text(text: str) -> list[float]:
    provider = EMBEDDING_PROVIDER.strip().lower()
    if provider in {"local_sentence_transformers", "sentence_transformers"}:
        from services.embeddings import MODEL_NAME, generate_embedding

        if EMBEDDING_MODEL and EMBEDDING_MODEL != MODEL_NAME:
            raise EmbeddingConfigurationError(
                f"EMBEDDING_MODEL={EMBEDDING_MODEL} does not match local model {MODEL_NAME}"
            )
        return _validate_embedding(generate_embedding(text))

    if provider not in {"openai_compatible", "openai"}:
        raise EmbeddingConfigurationError(
            "Set EMBEDDING_PROVIDER=local_sentence_transformers or openai_compatible"
        )
    if not EMBEDDING_API_URL or not EMBEDDING_API_KEY or not EMBEDDING_MODEL:
        raise EmbeddingConfigurationError("Embedding provider is missing API URL, key, or model")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            EMBEDDING_API_URL,
            headers={"Authorization": f"Bearer {EMBEDDING_API_KEY}"},
            json={"model": EMBEDDING_MODEL, "input": text},
        )
    if response.status_code >= 400:
        raise EmbeddingProviderError(f"Embedding provider failed with status {response.status_code}")

    data = response.json()
    try:
        vector = data["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        raise EmbeddingProviderError("Embedding provider response did not contain data[0].embedding") from exc
    return _validate_embedding(vector)
