# SAGE

SAGE is a FastAPI + React code-intelligence workspace for paste-code review, project ZIP/GitHub analysis, evidence-grounded findings, knowledge-assisted reasoning, and safe fix workflows.

The current implementation is built around a strict rule: deterministic evidence and validated repository context drive the product. LLM calls are used for explanation, quality review, and fix proposals, but they are not treated as authoritative proof by themselves.

## What SAGE Does

- Reviews pasted code snippets with deterministic rules plus AI quality review.
- Analyzes uploaded ZIP projects and imported GitHub repositories.
- Scores projects across security, reliability, code quality, testing, performance, and production readiness.
- Retrieves curated Sage engineering standards for each validated finding.
- Supports project chat with repository retrieval and knowledge RAG.
- Generates scoped fixes and applies only validated exact patches.
- Reanalyzes fixed code/projects and supports downloading applied fixes.

## Architecture

### Frontend

The React app lives in `client/`.

Primary UI areas:

- `client/src/App.jsx` - main Sage workspace shell, paste review, project views, Ask AI, finding detail, and V2 fix workflow.
- `client/src/api/client.js` - typed API wrapper for review, project import, chat, reasoning, fix generation, apply, and download.
- `client/src/components/` - supporting editor/history/project components.

The root app starts both frontend and backend with:

```bash
npm run dev
```

Frontend runs on:

```text
http://localhost:5173/
```

### Backend

The FastAPI backend lives in `server/`.

Important modules:

- `server/main.py` - FastAPI app registration.
- `server/routers/review.py` - paste-code review, per-finding knowledge retrieval, paste fix generation.
- `server/routers/projects.py` - ZIP/GitHub import, project analysis, scoring, reasoning, project fix/apply/download.
- `server/services/analyzer.py` - project mapping and metadata extraction.
- `server/services/analyzers/rules.py` - deterministic security, correctness, reliability, and production-readiness rules.
- `server/services/retrieval.py` - project chat retrieval over files/findings/import context.
- `server/services/patching.py` - exact structured patch validation and application.
- `server/knowledge/retrieval.py` - Sage knowledge hybrid retrieval.
- `server/knowledge/seed_data.py` - curated Sage engineering standards.
- `server/services/prompt_builder.py` - hardened prompts for review, chat, reasoning, and fixes.

Backend runs on:

```text
http://127.0.0.1:8000
```

## Review Pipeline

For pasted code:

1. Detect language mismatch when possible.
2. Run deterministic rules.
3. Run AI quality review for non-obvious correctness/maintainability issues.
4. Dedupe AI quality findings against deterministic findings.
5. Retrieve Sage knowledge per finding, not once per snippet.
6. Return one clean `Review findings` list to the UI.

The product UI hides internal RAG/debug metadata such as retrieval mode, top-k counts, raw vector scores, and retrieval method names. Internal logs still include finding IDs, retrieved knowledge IDs, methods, scores, and top-k counts for debugging.

## Finding-Scoped Knowledge Retrieval

Each finding builds its own retrieval query from:

- title/message
- rule/category
- exact evidence
- line/context
- reason/fix suggestion
- language

Retrieval ordering:

1. exact/curated rule match when available
2. semantic matches
3. dedupe
4. category/relevance filtering

Knowledge is shown as engineering guidance, not proof of a defect.

## Safe Fix Workflow

SAGE uses a preview-first patch model.

State model:

- `original_source` - exact code initially reviewed
- `working_source` - current editor/source after explicit user edits or applied fixes
- `generated_patch` - proposed preview only
- `applied_patches` - patches explicitly accepted by the user

### Generate Fix

Generate Fix only:

- calls the backend fix-generation endpoint
- validates the patch target
- stores the proposed patch
- renders Original / Proposed Preview / Diff
- determines `can_apply`

Generate Fix never mutates the editor or project files.

### Apply Fix

Apply Fix is the only normal paste-code action that mutates source.

Before applying, the patch validator checks:

- exact original snippet exists
- target occurs once
- replacement is scoped to that target
- source hash matches the generation base
- generated/applied patches do not overlap
- patch is well formed

Structured failure reasons:

- `target_not_found`
- `ambiguous_target`
- `stale_source`
- `overlapping_patch`
- `malformed_fix`

When validation passes:

- `can_apply = true`
- Apply Fix is enabled
- the editor is updated only after the user clicks Apply Fix
- finding state becomes `Fix applied`
- Reanalyze uses current working source
- Download Fixed File exports current working source only after a patch is applied

## Project Fix Workflow

For project findings:

1. Generate a scoped transform from project evidence.
2. Validate exact target snippets.
3. Apply only to the target file.
4. Preserve unrelated files and unrelated code.
5. Reanalyze the patched project.
6. Download a fixed ZIP that excludes unsafe paths and ignored secret files.

## MongoDB Atlas Vector Search

Trusted knowledge records live in the `sage_knowledge` collection by default. Uploaded project code is stored separately as project data and must not be ingested as Sage policy knowledge.

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

The default local model is `all-MiniLM-L6-v2`, which emits 384-dimensional vectors.

## Knowledge Ingestion

Curated records are defined in `server/knowledge/seed_data.py` and validated by `server/knowledge/schema.py`.

```bash
cd server
python -m knowledge.ingest
```

Ingestion upserts by `rule_id + version`, creates metadata indexes, stores `content_hash`, `embedding_model`, timestamps, and is safe to run repeatedly.

## Project Embeddings

Project embeddings use `server/services/embeddings.py`.

To backfill existing project documents:

```bash
cd server
python generate_embeddings.py
```

The script hydrates GridFS-backed file content, skips projects that already have a valid embedding, and stores the embedding on each project document.

## Environment

Create `server/.env` from `server/.env.example`.

Important variables:

```bash
GROQ_KEYS=key1,key2,key3
MONGO_URL=mongodb+srv://...
MONGO_DB_NAME=code_reviewer
KNOWLEDGE_COLLECTION=sage_knowledge
KNOWLEDGE_VECTOR_INDEX=sage_knowledge_vector_index
EMBEDDING_PROVIDER=local_sentence_transformers
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_DIMENSIONS=384
EMBEDDING_API_URL=
EMBEDDING_API_KEY=
```

Do not commit real secrets. `.env` is ignored by git.

## Local Development

Install everything:

```bash
npm install
```

Start frontend and backend together:

```bash
npm run dev
```

Backend only:

```bash
cd server
venv\Scripts\python -m uvicorn main:app --port 8000
```

Frontend only:

```bash
npm --prefix client run dev
```

## Testing

Run all backend tests:

```bash
pytest -q
```

Run frontend build:

```bash
npm --prefix client run build
```

Run frontend lint:

```bash
npm --prefix client run lint
```

Current coverage includes:

- deterministic analyzer true positives and false positives
- expanded JavaScript/Python detector rules
- knowledge schema and retrieval fallback
- finding-scoped paste-code RAG
- project vector failure fallback
- prompt injection hardening
- ZIP ingestion path traversal protection
- project patch apply/download safety
- paste fix structured patch validation
- preview-only Generate Fix workflow
- stale/missing/ambiguous/overlapping/malformed patch rejection

## Current Verification Snapshot

Latest local verification:

```text
pytest -q                         70 passed
npm --prefix client run build     passed
npm --prefix client run lint      passed with existing warnings only
```

Known lint warnings are React ergonomics warnings around synchronous state updates in effects and Fast Refresh component-only export guidance. They do not block the current hackathon workflow.

## Known Limitations

- The frontend still has a few non-blocking React lint warnings.
- The deterministic analyzers are heuristic, not full AST/dataflow analyzers.
- LLM-generated fixes are previewed and exact-patch validated, but complex multi-location edits still require manual review.
- Vector retrieval can fall back when Atlas/vector configuration is unavailable.
- This is a hackathon-ready prototype, not a hardened multi-tenant production deployment.
