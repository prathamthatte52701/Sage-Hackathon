Dedup improvements:

- Added normalized root-cause groups for command execution, deserialization, CORS, blocking async, SSRF, eval, and SQL injection.
- AI findings matching deterministic root cause, file, nearby line bucket, and evidence signature are merged instead of appended.
- Merged findings preserve provenance as ai_quality+deterministic.
- Different nearby findings with different evidence/root causes remain separate.

Focused tests:
- semantic duplicate deterministic+AI is merged: passed
- nearby different findings are not merged: passed
