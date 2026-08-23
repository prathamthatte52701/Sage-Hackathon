# PIPELINE_MAP.md — CODE MASTER AI architecture map

HEAD at audit time: `9d969cf63834168b1bbf7aed9cc6eff73f327cfb` (branch `main`)

## 1. Request lifecycle: Paste Code review

`POST /api/review` → `server/routers/review.py:759` (`review()`)

1. Language detection via regex signals: `review.py:224-251` (`detect_language`) — if strong TS/JS/PY syntax mismatches the selected language, `effective_language` overrides it.
2. Deterministic pass: `run_rules()` (`services/analyzers/rules.py:202`) over the full snippet → `deterministic.deterministic_findings` (`review.py:766`).
3. Pre-review RAG (`review.py:770-785`): builds a whole-snippet query from deterministic findings + regex "signal" scan (`build_paste_knowledge_query`, `review.py:315-342`), calls `retrieve_knowledge(top_k=6)`, reranked down to top 4 via lexical-overlap gate `rerank_paste_knowledge` (`review.py:716-756`, requires ≥2 shared tokens unless `retrieval_method=="exact_rule"`).
4. AI quality review: one `call_groq()` (`review.py:793-806`) with prompt from `build_quality_review_prompt` (`prompt_builder.py:41`), which embeds the pre-review knowledge. Up to 3 attempts total if JSON parsing fails (initial + 2 retries, each retry is a **new** Groq call, not a local reparse).
5. Grounding: `ground_issues(quality_issues, payload.code)` (`grounding.py:110`, called at `review.py:861`) — mechanical, not LLM-based (§7).
6. AI-vs-AI dedup: `dedupe_ai_findings` (`review.py:634-674`) merges same-root-cause duplicates (line proximity ≤2 + shared identifier or theme overlap).
7. Low-value style noise dropped: `drop_low_value_style_noise` (`review.py:677-686`).
8. AI-vs-deterministic dedup: `dedupe_quality_against_deterministic` (`review.py:600-611`, requires ≥2 shared tokens on the same line).
9. Finding-level RAG: `attach_issue_knowledge` (`review.py:689-713`) runs **per finding** (both deterministic and AI), `top_k=8` retrieved then reranked to 3 via `rerank_issue_knowledge` (`review.py:547-593`, category-gated + ≥2 token overlap).
10. `_apply_confidence_sanity_checks` (`review.py:176-181`): security findings with no line lose 0.2 confidence; critical+low-confidence forces `needs_human_review=True`.
11. Persisted via `save_review()` → Mongo `reviews` collection (`db/mongo.py:60-70`), keyed by client-supplied `session_id`.

Paste fix: `POST /api/review/fix` (`review.py:908`) → `build_transform_prompt` → `call_groq` (1 retry on bad JSON) → `_build_transform_response` computes diff via `build_patch_metadata` (`patching.py:73`) against the **original full snippet**, so `can_apply` reflects an exact-substring match, not a guess.

## 2. Request lifecycle: ZIP project upload/analysis

`POST /api/projects/upload` (`projects.py:274`) → `_project_from_zip_bytes` (`projects.py:161-271`):
- Guards (§11): 300MB zip cap, 600MB uncompressed cap, 2000 file cap, path-traversal/absolute/drive-letter rejection (`_is_unsafe_path`, `projects.py:73-89`), 100k-char per-file content cap (files over that keep `content=None`, i.e. never analyzed for imports/functions/rules — silently degraded, no warning surfaced for this specific cap).
- Only files whose language is in `SOURCE_LANGUAGES` or whose basename is a known manifest get `content` read at all (`_should_read_text`, `projects.py:92-94`); everything else (docs, assets, unknown extensions) is indexed by path only.
- Saved via `save_project()` → Mongo `projects` collection, file content moved into GridFS per-file (`db/mongo.py:119-138`), `content` key replaced with `content_ref`.

`POST /api/projects/{id}/analyze` (`projects.py:369`), single synchronous HTTP request, no job queue/polling:
1. `get_project()` rehydrates all file content from GridFS concurrently (`db/mongo.py:141-155`, `hydrate_file_content`).
2. `analyze_project()` (`services/analyzer.py:73-135`) — deterministic only: per-file `run_rules()` + per-language analyzer (`get_analyzer`, imports/functions/classes/routes extraction — python via `ast`, per `python_analyzer.py`; regex for JS). Runs over **every** file with content, no file-count cap. Findings deduped by exact `(file,line,rule,evidence)` tuple only (`analyzer.py:126-134`).
3. `run_ai_quality_review(analyzed)` (`services/project_review.py:130-186`): bounded to `MAX_FILES_REVIEWED=40` largest eligible files (`project_review.py:24,38`), chunked (§5/§11), `CONCURRENCY_LIMIT=4` semaphore, one `call_groq` per chunk with **no retry** on JSON-parse failure (`project_review.py:114-116`, silently returns `[]` — unlike paste review's 2 retries). Grounded per-chunk via `ground_issue` (chunk only, not full file — §7). Deduped against deterministic findings by `(file,line,category)` only (`project_review.py:79-88`) — coarser than paste path, and **no AI-vs-AI dedup at all** for project findings.
4. Coverage metadata (`files_discovered/eligible/reviewed/skipped`, `chunks_reviewed`, `groq_calls`) written to `project["ai_review_coverage"]` and later read by scoring (§9).
5. Updated fields persisted via `update_project()`.

`POST /api/projects/{id}/score` (`projects.py:418`) — separate call, `compute_score()` (§9), stored to `compliance_score`.

GitHub import (`POST /api/projects/github`, `projects.py:311-351`) **is implemented** — fetches `api.github.com/repos/{owner}/{repo}/zipball`, strips the zipball's `{repo}-{sha}/` wrapper, then runs through the exact same `_project_from_zip_bytes` path as upload. 30s httpx timeout on the GitHub fetch itself.

## 3. Request lifecycle: Reanalyze

`POST /api/projects/{id}/reanalyze` (`projects.py:648-713`):
- Requires a generated fix (`finding.transform.proposed_fix`) to already exist — this is "reanalyze with a specific fix applied," not a generic "rerun everything" button.
- Deep-copies the project (`copy.deepcopy`, `projects.py:666`), applies the fix via plain string `.replace(original, fixed, 1)` on the in-memory copy (**not** `apply_exact_replacement`'s ambiguity/overlap guard), resets derived fields, re-runs `analyze_project()` (deterministic only — reanalyze never re-invokes AI review) and `compute_score()`.
- Persists the patched project as a **new** Mongo document (`save_project`, fresh `_id`) rather than mutating the original — "reanalyze" produces a sibling project, not an in-place update.
- Returns resolved/remaining/new findings computed by `(file, rule)` key-set diff (`_finding_keys`, `projects.py:630-631`) — coarse; a fix that changes line number but not rule name registers as neither resolved nor new.
- Explicitly returns `behavior_verified: False` with a caveat string (`_verification_note`, `projects.py:634-645`) — honest that no tests are actually executed.

## 4. Request lifecycle: Ask AI / project chat

`POST /api/projects/{id}/chat` (`projects.py:837-898`):
1. Stage 1/2 retrieval (`retrieve_relevant_files`, `services/retrieval.py:173-296`) — pure keyword/path/import-graph matching, **no embeddings**, top 5 scored files + import-graph-related expansion up to `MAX_TOTAL_FILES=8`. This is the **sole** source of "project evidence"; if it returns `[]`, the endpoint short-circuits with a canned "doesn't appear to contain anything matching" answer **without ever calling the LLM** (`projects.py:848-854`).
2. Stage 3a (optional): engineering-knowledge RAG, only triggered if the question matches `_GUIDANCE_KEYWORDS` (`projects.py:825-834`).
3. Stage 3b (optional): cross-project semantic context (`retrieve_semantic_project_context`, `services/retrieval.py:299-378`) via a **separate** Atlas vector index (`vector_index`, one embedding per whole project, built by `generate_embeddings.py`) — finds *other* similar projects, explicitly labeled non-evidence in the prompt (`prompt_builder.py:364-368`), scoped to the same `session_id`.
4. `answer_project_question()` (`reasoning_engine.py:165-191`) → `build_chat_prompt` (`prompt_builder.py:371-436`) → 1 Groq call + 1 retry-on-bad-JSON. `_build_chat_answer` clamps `cited_files` to the actually-retrieved path set (`reasoning_engine.py:79-93`) — model cannot cite a file it wasn't shown, mechanically enforced.

## 5. Request lifecycle: Fix generation → view diff → apply fix → download

Project path, per finding:
- Generate: `POST /api/projects/{id}/findings/transform` (`projects.py:554-612`) → `build_finding_context` (full origin-file snippet ±8 lines + related files via import graph) → `generate_fix()` → `_enrich_transform` computes `diff`/`can_apply` against the **actual current file content** via `apply_exact_replacement` (dry-run) — source genuinely not touched at this stage.
- View diff: diff string already returned in the transform response. **`ProjectFindingCard.jsx` (which renders it) is dead code, never imported by the running app** (§12). In the real (paste) UI, `App.jsx:1580`'s "View Diff" button has `disabled={!fix}` but **no `onClick` handler at all** — the diff panel is shown unconditionally below it anyway (`App.jsx:1589`), so the button is vestigial, not broken-blocking.
- Apply: `POST /api/projects/{id}/fixes/apply` (`projects.py:720-782`) → `apply_exact_replacement` — raises `PatchError` (409) on `target_not_found`/`ambiguous_target`/`overlapping_patch`; only on success does `file_entry["content"]` mutate, `finding.fix_state="Applied"`, re-runs deterministic `analyze_project` + `compute_score`.
- Download: `GET /api/projects/{id}/download-fixed` (`projects.py:785-816`) — rebuilds ZIP from `project.files[].content` (post-apply state), skips `IGNORE_DIRS`/`.env`/`.pyc`, filename sanitized via regex.

Paste path: fix generated via `/api/review/fix`; apply happens **entirely client-side** in `App.jsx` (`applyFix`, `App.jsx:1309-1328`) against the in-editor `code` string, own overlap guard (`hasOverlappingGeneratedPatch`) — no backend call to apply. Download Fixed File / Download Patch (`App.jsx:1340-1347`) are also pure client-side, no backend endpoint involved.

## 6. Request lifecycle: History

`GET /api/reviews/history?session_id=` (`review.py:940-948`) → `get_history()` (`db/mongo.py:73-80`) — last 20 `reviews` docs for that session, sorted by `created_at` desc. This is **paste-review history only** — no equivalent project-analysis history endpoint exists.

## 7. Grounding — exact validation logic

`services/grounding.py`, `ground_issue` (`grounding.py:59-93`). Two mechanical checks, no second LLM call:
1. **Line range**: `issue.line` must be within `1..len(code.splitlines())` of the exact string passed in — for project review this is the **chunk**, not the full file (`project_review.py:124`), so it cannot catch a line number valid-looking within the chunk but wrong relative to the real file.
2. **Evidence existence**: whitespace-normalized substring match against source; falls back to checking every identifier-shaped token (5+ chars) in `evidence` exists somewhere in source tokens.

**Does NOT check** (explicit in module docstring, `grounding.py:18-26`): `missing_control`, `fix_suggestion`, `issue` text — by design (absence-based findings legitimately name things not in the source). Does not validate semantic correctness of the claim, that evidence and line number correspond, surrounding function/class context, or (project review) anything outside the shown chunk. A finding can pass grounding while semantically wrong, if its evidence string literally appears in-scope somewhere.

## 8. Deduplication — exact keys/logic used

Four different dedup implementations, inconsistent strength:
- `analyzer.py:126-134` (project, deterministic-only): exact tuple `(file, line, rule, evidence)`.
- `project_review.py:79-88` (project, AI-vs-deterministic): `(file, line, category)` only — two distinct security findings on the same line silently collapse into one. **No AI-vs-AI dedup exists for project findings at all.**
- `review.py:600-611` (paste, AI-vs-deterministic): same line + ≥2 shared tokens.
- `review.py:634-674` (paste, AI-vs-AI): line proximity ≤2 AND (shared 5+-char identifier OR ≥2 shared theme tokens at ≥50% overlap).

Net: paste path has materially stronger dedup than project path.

## 9. Scoring — 7 dimensions, source and partial-coverage handling

`services/scoring.py:126-296`, `compute_score(project)`. All 7 `CATEGORY_ORDER` keys always present; status ∈ `{evaluated, partial, not_evaluated}`.
- **security, code_quality**: severity deduction (critical 25/high 15/medium 8/low 3); status `partial` whenever `ai_review_coverage.files_skipped > 0` — score itself not further discounted, only the status label reflects partial coverage.
- **architecture**: findings + heuristic (≥5 API endpoints and no `services/` dir → -15).
- **api_design**: `not_evaluated` if zero `apiEndpoints` detected — confirms "no API endpoints → Not assessed, not 100" is already handled correctly in current code.
- **performance**: regex scan for blocking-call markers + findings; always `evaluated`/`not_evaluated`, never `partial` — inconsistent with security/code_quality's partial-awareness even though AI review can also surface performance issues.
- **testing**: pure file-presence heuristic (-40 if no test files found) — never `partial`, never AI-dependent.
- **production_readiness**: -20 no deployment files, -10 no dependency manifest, plus findings; `partial` when AI coverage incomplete.
- **Overall**: weighted average over non-`not_evaluated` categories only, renormalized.

Notable gap: AI-sourced "critical" findings are downgraded to "high" severity when converted to project findings (`_issue_to_project_finding`, `project_review.py:63-68`) — they get the 15-point deduction, not 25. Paste-path `Issue.severity` only allows `critical|medium|low` (no `high`), so this bucket is project-only, worth confirming against a live SSRF/IDOR test.

## 10. RAG — pipeline stages and thresholds

Core: `retrieve_knowledge()` (`knowledge/retrieval.py:258-330`).
1. **Exact/curated match** (`_exact_records`): metadata filter (language/framework/category) + `rule_id` match or `phrase_hit` or `strong_overlap` (≥2 shared non-generic tokens AND ≥30% of query's own tokens). Score fixed `1.0`, method `exact_rule`.
2. **Vector search** (Atlas `$vectorSearch`, index `sage_knowledge_vector_index`, `numCandidates=max(20,top_k*10)`, `limit=max(top_k,8)`) — `KNOWLEDGE_MIN_SCORE=0.55` discards weaker matches.
3. **Merge**: exact-first then semantic, deduped by `knowledge_id`, capped at `top_k`.
4. **Fallback**: fires only when Mongo/embedding unavailable — lexical overlap scoring, floor 1 shared token, can legitimately return fewer than top_k or zero.
5. **Per-caller reranking**, paste-specific only: `rerank_paste_knowledge` (top 4) and `rerank_issue_knowledge` (top 3, category-gated + ≥2 token overlap). Project-path callers call `retrieve_knowledge` directly with category filtering but **no additional reranking layer** — project path trusts base retrieval more than paste path does.

Query construction differs by caller: pre-review (whole-snippet regex signal scan), per-finding paste (±3/+2 line window), project finding (rule+evidence+message+700-char context), chat guidance (question verbatim). All pass through `redact_sensitive_query_text` which regex-redacts password/secret/api_key/token literal values before the query leaves the process.

## 11. Concrete numeric limits (file:line)

| Limit | Value | Location |
|---|---|---|
| Paste code max length | 7000 chars | `models/schemas.py:15` |
| Chat question max length | 500 chars | `models/schemas.py:70` |
| ZIP max size | 300MB | `routers/projects.py:27` |
| ZIP max uncompressed (bomb guard) | 600MB | `routers/projects.py:28` |
| ZIP max file count | 2000 | `routers/projects.py:29` |
| Per-file content read cap | 100,000 chars | `routers/projects.py:30` (larger files keep `content=None`, silently unanalyzed) |
| Max path depth | 20 | `routers/projects.py:31` |
| Project AI review: max files reviewed | 40 (largest-first) | `services/project_review.py:24,38` |
| Project AI review: max chunk size | 6000 chars | `services/project_review.py:25` |
| Project AI review: max chunks/file | 2 (no overlap; remainder past chunk 2 never reviewed) | `services/project_review.py:26,42-59` |
| Project AI review: concurrency | 4 (asyncio.Semaphore) | `services/project_review.py:27,146` |
| Groq per-attempt timeout | 20s | `services/groq_client.py:10` |
| Groq max attempts | 3, backoff 0/0.5s/1.0s | `services/groq_client.py:11,23` (worst case ~62s per call) |
| Groq max output tokens | 3000, reasoning_effort=low | `services/groq_client.py:21-22` |
| Groq key cooldown after 401/429 | 120s | `services/groq_client.py:9` |
| Embedding provider timeout | 30s | `knowledge/embeddings.py:56` |
| RAG semantic score floor | 0.55 | `config.py:28` |
| RAG fallback lexical floor | 1 shared token | `knowledge/retrieval.py:192` |
| Chat: max related files | 8 | `services/retrieval.py:52` |
| Chat: context chars/file | 1500 | `services/retrieval.py:25` |
| Finding context: related-file budget | 6000 chars total | `services/context_expansion.py:4` |
| IP rate limit | 30 req / 60s window | `services/rate_limit.py:11-12` |
| Frontend axios default timeout | 30s | `client/src/api/client.js:5` |
| Frontend upload/analyze/score/github timeout | 60s | `client/src/api/client.js:66,91,100,80` |
| Backend HTTP request timeout | none — no `request.is_disconnected()` check in `analyze_project_by_id`, coroutine runs to completion server-side even after frontend's 60s timeout fires client-side |

Derived: worst-case project AI-review stage = 40 files × 2 chunks = 80 chunks, 4-way concurrent → 20 sequential batches. This is the architectural mechanism behind previously-observed large-project timeouts (measured live in Phase 5/19 below).

## 12. Frontend-to-backend endpoint map + dead UI controls

All wiring lives in `client/src/App.jsx` (1708 lines) via `client/src/api/client.js`. Every exported client.js function (`reviewCode, generatePasteFix, explainIssue, getHistory, uploadProject, importFromGithub, analyzeProject, scoreProject, transformFinding, reasonFinding, chatAboutProject, reanalyzeProject, applyProjectFix, fixedProjectZipUrl`) is imported and called from `App.jsx`.

**Dead code — 10 of 13 component files never imported anywhere in the running app**: `IssueCard.jsx`, `IssueList.jsx`, `ProjectUpload.jsx`, `ProjectChat.jsx`, `HistoryPanel.jsx`, `ExplainChat.jsx`, `ReviewButton.jsx`, `ScanProgress.jsx`, `ProjectFindingCard.jsx`, `ProjectFindingsList.jsx` — ~1300 lines. `App.jsx` reimplements equivalent UI inline instead. Any UI-regression testing must target the inline `App.jsx` implementation, not these files.

**Dead button**: `App.jsx:1580` — paste-review "View Diff" button has `disabled={!fix}` but no `onClick`; redundant not broken (diff panel already shows unconditionally below it).

Backend routes actually exposed (confirmed live via `/openapi.json` on running server):
```
POST /api/review
POST /api/review/fix
GET  /api/reviews/history
POST /api/explain-bug
POST /api/projects/upload
POST /api/projects/github
GET  /api/projects/{project_id}
POST /api/projects/{project_id}/analyze
POST /api/projects/{project_id}/score
POST /api/projects/{project_id}/findings/reason
POST /api/projects/{project_id}/findings/transform
POST /api/projects/{project_id}/reanalyze
POST /api/projects/{project_id}/fixes/apply
GET  /api/projects/{project_id}/download-fixed
POST /api/projects/{project_id}/chat
GET  /health
```
