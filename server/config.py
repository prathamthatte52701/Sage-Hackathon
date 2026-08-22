import os

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEYS = [k.strip() for k in os.getenv("GROQ_KEYS", "").split(",") if k.strip()]
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

MONGO_URL = os.getenv("MONGO_URL", "")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "code_reviewer")

KNOWLEDGE_COLLECTION = os.getenv("KNOWLEDGE_COLLECTION", "sage_knowledge")
KNOWLEDGE_VECTOR_INDEX = os.getenv("KNOWLEDGE_VECTOR_INDEX", "sage_knowledge_vector_index")
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "0") or "0")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_API_URL = os.getenv("EMBEDDING_API_URL", "")

# Minimum Atlas $vectorSearch cosine score for a semantic (non-exact-rule)
# knowledge match to be considered relevant enough to use. Chosen from
# observed score distribution on this KB (~100 records, all-MiniLM-L6-v2):
# unrelated/nonsense queries still scored ~0.52-0.64, so there's no crisp
# separation gap -- this threshold trades some weak-but-real matches for
# fewer irrelevant ones, and is intentionally overridable per deployment/KB size.
KNOWLEDGE_MIN_SCORE = float(os.getenv("KNOWLEDGE_MIN_SCORE", "0.55"))
