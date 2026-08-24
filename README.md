# CODE MASTER AI

## Evidence-First Security Review for Real Repositories

CODE MASTER AI is a repository security workspace built around a deliberately strict idea:

> **A security finding should be traceable to concrete code evidence, not an AI hunch.**

Upload a ZIP, import a public GitHub repository, or review a focused snippet. CODE MASTER AI maps the codebase, runs deterministic checks, presents grounded findings, retrieves rule-specific guidance, generates a scoped remediation proposal, validates the patch, and rescans the stored source after an explicit apply.

CODE MASTER AI is designed to prefer **no finding** over a vague or unprovable warning.

Current product capabilities include Python repository analysis, deterministic security review with curated RAG guidance, Hacker Mode adversarial review, Brutal Audit production-readiness review, Fix All remediation, Architecture View, Blast Radius View, and ZIP/GitHub repository ingestion.

---

## The Product Contract

CODE MASTER AI uses a closed-world security model. V1 actively certifies eleven deterministic rule families; dependency-risk scanning remains planned until a real manifest advisory detector is wired into the same gate.

| # | Canonical family | Examples of evidence CODE MASTER AI must require |
| --- | --- | --- |
| 01 | Hardcoded secrets | Credential-like literal plus contextual evidence |
| 02 | SQL injection | Untrusted input reaching unsafe SQL construction and execution |
| 03 | NoSQL injection | Untrusted object/operator flow into a recognized query context |
| 04 | Command injection | Unsafe command construction or shell execution flow |
| 05 | SSRF | Attacker-influenced destination reaching an outbound network sink |
| 06 | Path and file security | Unsafe file path, upload, archive, or filesystem operation |
| 07 | Unsafe deserialization | A concrete unsafe deserializer call and relevant input context |
| 08 | Dynamic execution | Real `eval` or `exec` call nodes, never comments or prose |
| 09 | TLS and CORS misconfiguration | Concrete insecure transport or credentialed CORS configuration |
| 10 | Weak crypto or randomness | Weak primitive in a security-sensitive use case |
| 11 | Auth and session security | Deterministically provable session or ownership defect |

AI, RAG, and the frontend do **not** get to invent findings. Their role is to enrich deterministic, evidence-backed results with explanation, standards guidance, and safe remediation proposals.

### What CODE MASTER AI refuses to do

- Turn comments, documentation, variable names, or generic code smells into vulnerabilities.
- Present model confidence as proof.
- Mutate source code while generating a fix.
- Apply a patch when the target is missing, ambiguous, stale, overlapping, or malformed.
- Pretend a missing source file or validation result is available.

Only test-backed detector behavior should be treated as implemented or certified. Dependency risk is part of the product direction, but it is not an active V1 finding family.

---

## From Repository to Verified Change

```text
ZIP / GitHub repository / pasted code
                |
                v
      Repository map and deterministic analysis
                |
                v
      Evidence-backed security finding
                |
                v
      Rule-aware guidance and scoped fix proposal
                |
                v
      Exact-target patch validation + diff preview
                |
                v
      Explicit apply to one stored source file
                |
                v
      Reanalyze the current repository source
```

### Safe fix lifecycle

1. **Generate** produces a preview only. Source does not change.
2. **Validate** checks exact target presence, uniqueness, source hash, overlap, and patch shape.
3. **Preview** shows the proposed diff and backend validation state.
4. **Apply** performs one structured patch only when `can_apply` is true.
5. **Reanalyze** runs the same canonical analysis flow against the newly stored source.

When validation fails, the API returns a specific reason such as `target_not_found`, `ambiguous_target`, `stale_source`, `overlapping_patch`, or `malformed_fix`.

---

## The Complete CODE MASTER AI Flow, A to Z

This is the exact product journey for a repository review.

| Step | User action | CODE MASTER AI does | What remains true |
| --- | --- | --- | --- |
| A | Open the workspace | Starts in demo mode or validates the configured session mode | The browser never chooses an owner identity |
| B | Upload a ZIP or enter `owner/repo` | Validates archive/repository input and creates a stored project | Archive paths, sizes, duplicate paths, and binary files are handled safely |
| C | Start analysis | Enqueues one canonical analysis job | The request returns quickly instead of holding the browser open for a long scan |
| D | Watch scan state | Polls the job until it is `completed`, `partial`, or `failed` | The UI does not invent completion or percentage progress |
| E | Open the report | Loads project metadata, findings, score, and source revision state | Metadata reads do not need to hydrate every source file |
| F | Select a finding | Fetches the real stored file and highlights the evidence location | If source is unavailable, CODE MASTER AI says so rather than fabricating code |
| G | Ask for reasoning | Uses the verified finding and repository context to retrieve relevant guidance | Guidance explains a finding; it does not create one |
| H | Generate a fix | Produces a scoped proposal, unified diff, source hash, and validation result | No source code changes during generation or preview |
| I | Review validation | Checks target presence, uniqueness, source freshness, overlap, and patch structure | Apply stays disabled unless the backend returns `can_apply: true` |
| J | Apply the fix | Changes only the validated target file and records the patch | A stale, ambiguous, duplicate, or malformed patch is rejected safely |
| K | Reanalyze | Queues the same canonical pipeline against the current stored source | Reanalysis never applies the proposal a second time |
| L | Download | Streams a fixed ZIP with changed source plus preserved unrelated project files | The download reflects stored source, not a client-side approximation |

### Request and data flow

```text
Browser
  |
  +-- POST upload/import ---------------------------> Project router
  |                                                     |
  |                                                     +-- normalized project + owner-scoped persistence
  |
  +-- POST analyze/reanalyze -----------------------> Analysis job service
  |                                                     |
  |                                                     +-- deterministic analysis
  |                                                     +-- guarded enrichment
  |                                                     +-- stable findings + revisions
  |
  +-- GET job / project / file ---------------------> Owner-scoped reads
  |
  +-- POST finding transform -----------------------> Patch validation metadata + diff
  |
  +-- POST apply -----------------------------------> One structured source mutation
  |
  +-- GET download-fixed ---------------------------> Streamed ZIP of stored project state
```

The same server-side identity travels through every project, job, finding, file, patch, chat, and download request. Frontend state is presentation state; persisted source and backend validation are the authority.

---

## Exact Project Flow and API Contract

This section documents the request sequence used by the project workspace. It is the contract the frontend follows today.

### 1. Create a project

Choose one ingestion path:

```text
POST /api/projects/upload
Content-Type: multipart/form-data

file       = repository.zip
session_id = browser-session-id
```

or:

```json
POST /api/projects/github
{
  "repo_url": "owner/repository",
  "session_id": "browser-session-id"
}
```

The backend assigns the owner from `get_request_user()`. `session_id` supports client history/UX; it is not an authorization identity. A successful response includes `project_id`, normalized project metadata, and any ingestion warnings.

### 2. Analyze asynchronously

```text
POST /api/projects/{project_id}/analyze
-> 202 Accepted
{
  "job_id": "...",
  "status": "queued",
  "created": true
}
```

The client polls:

```text
GET /api/analysis-jobs/{job_id}
```

Possible job states are:

```text
queued -> running -> completed
                 -> partial
                 -> failed
```

For a duplicate request while the same project is already being analyzed, the backend returns the existing active job rather than running another expensive analysis.

### 3. Load report and score

After a terminal successful job state, the client refreshes the project and score:

```text
GET  /api/projects/{project_id}
POST /api/projects/{project_id}/score
```

The project response carries findings, analysis state, and source metadata. It intentionally does not need to hydrate every GridFS-backed source file. The UI loads a selected file only when needed:

```text
GET /api/projects/{project_id}/files/{file_path}
```

### 4. Operate on a stable finding

Every analyzed finding has a deterministic `finding_id`. New frontend calls use that identity, never a synthetic `finding_index = -1` fallback.

```json
POST /api/projects/{project_id}/findings/reason
{ "finding_id": "stable-finding-id" }
```

```json
POST /api/projects/{project_id}/findings/transform
{ "finding_id": "stable-finding-id" }
```

The transform response contains the proposed original/replacement snippets, diff, source hash, target span, `can_apply`, a specific `apply_failure_reason`, and backend-produced validation checks.

### 5. Apply exactly once

```json
POST /api/projects/{project_id}/fixes/apply
{ "finding_id": "stable-finding-id" }
```

The patch engine validates the current stored file before it writes:

```text
original target exists
target occurs exactly once
stored source hash still matches
replacement is well formed
patch does not overlap an existing affected span
```

Only the selected file is changed. A successful apply increments `source_revision` and leaves the previous analysis stale until rescan. Reapplying an already-applied or stale transform is rejected instead of modifying the file again.

### 6. Reanalyze the stored source

```text
POST /api/projects/{project_id}/reanalyze
-> 202 Accepted { job_id, status, created }
```

Reanalysis uses the same analysis pipeline as the initial scan. It does not rerun the replacement or depend on an old finding. Once its job completes, the client repeats the project and score refresh:

```text
GET  /api/projects/{project_id}
POST /api/projects/{project_id}/score
```

At rest, freshness is expressed by the revision relationship:

```text
analysis_revision == source_revision  -> report describes current stored source
analysis_revision != source_revision  -> report is stale; reanalysis is required
```

### 7. Export the resulting project

```text
GET /api/projects/{project_id}/download-fixed
```

The backend streams a ZIP from persisted project state. It includes changed source plus preserved unrelated text and binary project files, while refusing unsafe archive paths.

### Failure semantics

| Situation | Expected behavior |
| --- | --- |
| Invalid archive or GitHub URL | Controlled `400` with an actionable error message |
| Project, job, or file is not owned/does not exist | Controlled `404` without leaking another project's data |
| Analysis cannot complete | Job becomes `failed` or `partial`; the UI does not claim a clean scan |
| AI enrichment fails | Deterministic results remain; coverage is marked partial where applicable |
| Generated patch no longer matches source | Controlled `409`/validation failure; source is unchanged |
| File source cannot be loaded | UI shows `Source unavailable`, not generated placeholder code |

---

## What You Can Do Today

- Analyze Python repositories from ZIP archives or public GitHub imports.
- Review pasted Python, JavaScript, TypeScript, Java, or C/C++ snippets.
- Run deterministic security review backed by rule-specific RAG guidance.
- Inspect findings, evidence, source locations, and rule-aware guidance.
- Load the real stored file for a finding instead of a fabricated code preview.
- Generate and validate a focused fix before applying it.
- Run Fix All across confirmed security findings with per-finding validation.
- Use Hacker Mode for independent attacker-perspective analysis without RAG.
- Use Brutal Audit for production-readiness review without changing normal findings.
- Use Architecture View to inspect grounded Python components and imports.
- Use Blast Radius View to understand which components, routes, and sinks are affected if a Python component fails.
- Rescan a project after a patch and download a fixed project ZIP.
- Ask repository-grounded questions through project chat and curated engineering knowledge.
- Run the hackathon/demo experience without signup or login.

---

## Architecture

```text
React + Vite workspace
        |
        | HTTP API
        v
FastAPI application
        |
        +-- Repository ingestion and ZIP safety controls
        +-- Deterministic analyzers and finding normalization
        +-- Background analysis jobs
        +-- Patch validation and structured apply engine
        +-- Project metadata, GridFS-backed source, and downloads
        +-- Curated knowledge retrieval and guarded LLM enrichment
        +-- MongoDB persistence and owner-scoped project access
```

| Area | Key modules |
| --- | --- |
| Frontend workspace | `client/src/App.jsx`, `client/src/components/` |
| API client and polling | `client/src/api/client.js` |
| Application setup | `server/main.py` |
| Project ingestion, jobs, findings, patches | `server/routers/projects.py` |
| Snippet review and fixes | `server/routers/review.py` |
| Deterministic rules | `server/services/analyzers/rules.py` |
| Exact patch validation | `server/services/patching.py` |
| Hacker Mode | `server/services/hacker_lens.py`, `client/src/components/HackerLens.jsx` |
| Brutal Audit | `server/services/brutal_audit.py`, `client/src/components/BrutalAudit.jsx` |
| Blast Radius View | `server/services/blast_radius.py`, `client/src/components/BlastRadiusView.jsx` |
| Project retrieval | `server/services/retrieval.py` |
| Curated knowledge | `server/knowledge/` |
| MongoDB and GridFS | `server/db/mongo.py` |

---

## Quick Start

### Prerequisites

- Node.js 20+
- Python 3.11+
- MongoDB or MongoDB Atlas for persistence
- Optional: Groq API keys for AI explanation and fix enrichment

### Install

```bash
npm install
```

The root install script creates the backend virtual environment and installs frontend dependencies.

### Configure

Create `server/.env` from `server/.env.example`.

```env
MONGO_URL=mongodb+srv://...
MONGO_DB_NAME=code_reviewer

# Demo mode is the current default.
AUTH_ENABLED=false
DEMO_USER_ID=demo-user

# Optional AI enrichment.
GROQ_KEYS=key1,key2
```

For the frontend, copy `client/.env.example` if you need to override defaults:

```env
VITE_API_URL=http://localhost:8000
VITE_AUTH_ENABLED=false
```

### Run

```bash
npm run dev
```

- Workspace: `http://localhost:5173`
- API: `http://localhost:8000`
- Health probe: `http://localhost:8000/health`

Run either side separately when needed:

```bash
npm run dev:server
npm run dev:client
```

---

## Demo Mode and Auth

Hackathon builds default to a deliberate single-user demo mode:

```env
AUTH_ENABLED=false
```

In this mode, every request receives the same internal server-owned demo identity. The browser never supplies an owner ID. This keeps the persistence model structurally consistent while letting the workspace open directly without a login screen or `/auth/me` startup call.

The auth implementation remains intact. Set both flags to `true` to restore the cookie/JWT flow:

```env
# server/.env
AUTH_ENABLED=true

# client/.env
VITE_AUTH_ENABLED=true
```

When auth is enabled, configure a strong `JWT_SECRET` and appropriate production cookie/CORS settings.

---

## Repository Ingestion Guarantees

CODE MASTER AI treats uploaded archives as untrusted input. ZIP processing includes controls for:

- Path traversal, absolute paths, and excessive path depth.
- Duplicate canonical file paths.
- Maximum archive size, file count, aggregate expansion, and per-file expansion.
- GitHub ZIP wrapper-directory normalization.
- Binary asset preservation alongside readable source files.
- On-demand source hydration: metadata requests do not need to load every source body.

The source viewer fetches the requested project file only. If a file is unavailable, the UI says so instead of manufacturing a snippet.

---

## Analysis Jobs

Project analysis and reanalysis are asynchronous.

```text
POST /api/projects/{project_id}/analyze
  -> 202 { job_id, status }

GET /api/analysis-jobs/{job_id}
  -> queued | running | completed | partial | failed
```

The frontend polls the job state before loading fresh project results. Repeated requests for the same active project analysis are deduplicated rather than launching duplicate expensive work.

---

## API Surface

| Capability | Endpoint |
| --- | --- |
| Upload ZIP | `POST /api/projects/upload` |
| Import GitHub repository | `POST /api/projects/github` |
| Start analysis | `POST /api/projects/{id}/analyze` |
| Read analysis job | `GET /api/analysis-jobs/{job_id}` |
| Fetch project metadata | `GET /api/projects/{id}` |
| Fetch a real project file | `GET /api/projects/{id}/files/{path}` |
| Explain a finding | `POST /api/projects/{id}/findings/reason` |
| Generate a fix proposal | `POST /api/projects/{id}/findings/transform` |
| Apply a validated fix | `POST /api/projects/{id}/fixes/apply` |
| Reanalyze current source | `POST /api/projects/{id}/reanalyze` |
| Download fixed project | `GET /api/projects/{id}/download-fixed` |
| Project chat | `POST /api/projects/{id}/chat` |
| Hacker Mode | `POST /api/projects/{id}/hacker-lens` |
| Brutal Audit | `POST /api/projects/{id}/brutal-audit` |
| Blast Radius | `GET /api/projects/{id}/blast-radius` |

---

## Quality Gates

Run backend tests from the repository root:

```bash
pytest -q
```

Build the frontend:

```bash
npm --prefix client run build
```

Lint the frontend:

```bash
npm --prefix client run lint
```

The test suite covers the core contracts behind the product: deterministic analysis, patch safety, stale-source handling, ZIP ingestion, owner scoping, job lifecycle behavior, demo mode, source hydration, prompt hardening, and regression cases.

---

## Operating Principles

1. **Evidence before explanation** - model output cannot substitute for code evidence.
2. **One finding, one identity** - finding IDs are deterministic and do not depend on UI array position.
3. **Preview before mutation** - generating a fix never changes source.
4. **Current source is truth** - reanalysis runs against stored source after an explicit apply.
5. **Missing data stays missing** - no fake code, fake validation, or fake success states.
6. **Security scope stays narrow** - precision matters more than a large warning count.

---

## Important Limitations

CODE MASTER AI is an evidence-first security workspace, not a replacement for a full secure-development program or expert review. Static analysis has language and semantic limits; some high-confidence remediation still needs human review. AI features can enrich a verified finding, but they are not an authority for discovering or proving one.

The closed-world model is intentionally phase-gated. Do not represent a rule family as certified until its positive, negative, adversarial, determinism, and regression gates are all green.

---

## Build With Proof

CODE MASTER AI is for teams who would rather see fewer alerts with a clear evidence trail than an impressive-looking pile of guesses.

**Scan the repository. Follow the evidence. Apply only what can be validated.**
