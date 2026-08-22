MODEL_NAME = "all-MiniLM-L6-v2"

_model = None


def _get_model():
    # Constructing SentenceTransformer loads a real model into memory (tens
    # of MB, a real multi-second cost) -- doing that at module-import time
    # means it happens the moment anything merely imports this module, on
    # whatever request path/thread got there first, not necessarily an
    # embedding request. Deferred to first real use and cached, so the cost
    # is paid once, by the call that actually needs it, off the event loop
    # (embed_text() already wraps generate_embedding in asyncio.to_thread).
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME)
    return _model


def generate_embedding(text: str) -> list[float]:
    return _get_model().encode(text).tolist()
