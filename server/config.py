import os

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEYS = [k.strip() for k in os.getenv("GROQ_KEYS", "").split(",") if k.strip()]
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_GLOBAL_CONCURRENCY = int(os.getenv("GROQ_GLOBAL_CONCURRENCY", "4") or "4")
PROJECT_AI_CALL_BUDGET = int(os.getenv("PROJECT_AI_CALL_BUDGET", "48") or "48")

MONGO_URL = os.getenv("MONGO_URL", "")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "code_reviewer")

# Demo builds deliberately use one server-owned identity. This preserves the
# ownership schema without accepting a user identity from the browser.
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").strip().lower() == "true"
DEMO_USER_ID = os.getenv("DEMO_USER_ID", "demo-user").strip() or "demo-user"

# No fallback: a guessable default here would let enabled auth run
# "successfully" with a forgeable session secret.
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60") or "60")

# Phase 1 authentication foundation uses server-side opaque sessions. The raw
# session/verification token is never stored; only an HMAC-SHA256 digest bound
# to SESSION_SECRET is persisted. SESSION_SECRET falls back to JWT_SECRET so an
# existing deployment that already generated a strong JWT_SECRET keeps working,
# but a dedicated SESSION_SECRET is preferred.
SESSION_SECRET = os.getenv("SESSION_SECRET", "") or JWT_SECRET
# How long an issued session stays valid before the server rejects it.
SESSION_EXPIRE_MINUTES = int(os.getenv("SESSION_EXPIRE_MINUTES", "60") or "60")
# How long an email-verification token stays valid.
VERIFICATION_TOKEN_MINUTES = int(os.getenv("VERIFICATION_TOKEN_MINUTES", "1440") or "1440")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").strip().lower() != "false"

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

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

# Request size limits (bytes)
MAX_JSON_SIZE = int(os.getenv("MAX_JSON_SIZE", "1048576"))  # 1 MB default for JSON bodies
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", "314572800"))  # 300 MB default for uploads
