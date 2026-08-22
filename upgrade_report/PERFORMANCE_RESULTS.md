Performance notes:

- Project AI review remains bounded:
  - MAX_FILES_REVIEWED = 40
  - MAX_CHUNKS_PER_FILE = 2
  - CONCURRENCY_LIMIT = 4
- Structural AST parsing is local and best-effort; syntax errors degrade safely.
- Deterministic scanning now uses full source content for supported files, trading memory for correctness on large-file tail coverage.

Measured test timings:
- Focused backend test set: 24 passed in 0.19s pytest time.
- Full backend unit suite after implementation: 127.80s wall time with live/AI-dependent tests included.
- Frontend build: passed in under 1s reported Vite build time.
