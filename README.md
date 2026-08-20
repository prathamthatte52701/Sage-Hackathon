# SAGE

SAGE is a FastAPI + React code review prototype. This pass keeps the existing app structure and strengthens the backend review pipeline around deterministic evidence, repository context, trusted knowledge retrieval, LLM reasoning, fix generation, and static re-analysis.

## Architecture

Project ZIP upload and GitHub import both normalize repositories through `server/routers/projects.py`. Project analysis then runs:

1. language and framework detection from file paths/manifests,
2. repository mapping in `server/services/analyzer.py`,
3. per-language extraction in `server/services/analyzers/`,
4. deterministic rules in `server/services/analyzers/rules.py`,
5. import-graph context expansion in `server/services/context_expansion.py`,
6. trusted knowledge retrieval in `server/knowledge/retrieval.py`,
7. Groq-backed reasoning/fix generation in `server/services/reasoning_engine.py`,
8. static re-analysis and scoring in `server/routers/projects.py` and `server/services/scoring.py`.

The LLM is not the detection authority. It receives an existing finding, code evidence, related files, curated knowledge, and standards. Prompts explicitly treat repository content as untrusted data.

## MongoDB Atlas Vector Search

Trusted knowledge records live in the `sage_knowledge` collection by default. Uploaded project code is stored separately as project data and must not be ingested as SAGE policy knowledge.

Atlas Vector Search index:

```json
{
  "name": "sage_knowledge_vector_index",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      {
        "type": "vector",
        "path": "embedding",
        "numDimensions": 384,
        "similarity": "cosine"
      },
      { "type": "filter", "path": "category" },
      { "type": "filter", "path": "language" },
      { "type": "filter", "path": "framework" },
      { "type": "filter", "path": "severity" },
      { "type": "filter", "path": "rule_id" },
      { "type": "filter", "path": "version" }
    ]
  }
}
```

Set `numDimensions` to match `EMBEDDING_DIMENSIONS` for your configured embedding model. The default local model in `server/services/embeddings.py` is `all-MiniLM-L6-v2`, which emits 384-dimensional vectors.

## Knowledge Ingestion

Curated records are defined in `server/knowledge/seed_data.py` and validated by `server/knowledge/schema.py`.

```bash
cd server
python -m knowledge.ingest
```

Ingestion upserts by `rule_id + version`, creates metadata indexes, stores `content_hash`, `embedding_model`, and timestamps, and is safe to run repeatedly.

## Project Embeddings

`server/services/embeddings.py` uses `all-MiniLM-L6-v2` and returns 384-dimensional vectors. To backfill existing project documents after installing dependencies and confirming `MONGO_URL`:

```bash
cd server
python generate_embeddings.py
```

The script hydrates GridFS-backed file content, skips projects that already have a 384-dimensional embedding, and stores the embedding on each `projects` document.

## Environment

Copy `server/.env.example` and configure:

```bash
GROQ_KEYS=...
MONGO_URL=...
MONGO_DB_NAME=code_reviewer
KNOWLEDGE_COLLECTION=sage_knowledge
KNOWLEDGE_VECTOR_INDEX=sage_knowledge_vector_index
EMBEDDING_PROVIDER=local_sentence_transformers
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_DIMENSIONS=384
EMBEDDING_API_URL=...
EMBEDDING_API_KEY=...
```

If vector retrieval is unavailable, SAGE uses deterministic curated-knowledge fallback and records that fallback mode instead of pretending vector search succeeded.

## Local Development

```bash
npm install
npm run dev
```

Backend only:

```bash
cd server
python -m uvicorn main:app --reload --port 8000
```

Frontend only:

```bash
cd client
npm run dev
```

## Testing

Default tests are deterministic and do not require Groq, Atlas, or an embedding provider:

```bash
python -m pytest tests
```

Current test files cover analyzer false positives/true positives, JS route extraction, ZIP path traversal, context expansion, scoring heuristics, knowledge schema validation, and retrieval fallback.

In this execution environment, Python and `pip` were not available on PATH and the checked-in venv points at a missing interpreter, so backend tests could not be run here. The frontend production build was verified with:

```bash
npm.cmd --prefix client run build
```

## Known Limitations

This repository is not yet a complete implementation of every production-review requirement. The current pass does not include full JS/TS AST parsing, complete category-wide knowledge coverage, full LLM/DB failure test matrices, large-repository performance tests, or a complete CI pipeline.
