Implemented scoped main-upgrade changes:

- Added Python AST structural analyzer in server/services/structural/.
- Integrated structural metadata into project analysis as structuralMetadata.
- Replaced project AI review chunking with Python function/class-aware chunks when parsing succeeds.
- Preserved complete text content for supported source files during ZIP/GitHub ingestion so deterministic rules can scan large-file endings.
- Added explicit large-file warnings instead of silently dropping content.
- Expanded AI review coverage metadata with eligible_files, deterministic_files, ai_reviewed_files, ai chunk totals/completions, failed_ai_chunks, semantic_coverage, and partial_reasons.
- Strengthened deterministic+AI semantic deduplication using normalized root-cause groups and evidence keys.
- Preserved critical severity from AI project findings instead of down-ranking critical to high.
- Ensured reanalysis/apply-fix clears derived structural metadata.

Frontend redesign was intentionally avoided.
