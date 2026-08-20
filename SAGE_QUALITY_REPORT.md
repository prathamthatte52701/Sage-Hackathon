# SAGE Quality Report

This report is generated from actual local test execution. Update it after running:

```bash
server\venv\Scripts\pytest tests
```

No external LLM, embedding provider, or MongoDB Atlas service is required for the default deterministic tests.

## Latest Local Attempt

Backend status: not executed in this sandbox.

Reason: `server/venv` points to a missing Python executable and neither `python` nor `py` is available on PATH.

Frontend status: passed.

Command:

```bash
npm.cmd --prefix client run build
```

Result: Vite production build completed successfully.
