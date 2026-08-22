Large-project reliability changes:

- Source ingestion now keeps full content for supported text/source files instead of setting content=None above 100000 characters.
- Deterministic rules therefore scan through the end of huge files.
- New focused test confirms a hardcoded secret on line 12001 is detected.
- Oversize source files are marked with large_file=true and warning text.
- AI review remains bounded to 40 files and 2 chunks/file, but coverage now explicitly reports partial semantic coverage when files or chunks are skipped.

Not fully implemented in this pass:
- Persistent background job API with polling.
- End-to-end 10k/20k LOC browser upload regression.
