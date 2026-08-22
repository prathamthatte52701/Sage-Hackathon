RAG status:

- Existing finding-specific query construction and query-aware fallback were preserved.
- No knowledge-base expansion was performed.
- Full RAG regression was not rerun separately beyond the full unit suite because several tests depend on live external services.

Remaining risk:
- Some fallback records can still be generic when vector retrieval is unavailable.
