# Phase P0 — Architecture & Contracts
**Outcome:** App skeleton, routers, models, config, mocks.

> **Dependency whitelist (MUST FOLLOW)**
>
> - Python dependencies are allowed **only** if listed in `requirements.txt` (core) or `requirements-optional.txt` (extras).
> - You may not add/import any library that is not listed in one of those files.
> - If a new dependency is needed, STOP and update the requirements files first (subject to review), then proceed.
> - This whitelist is the barrier for adding libraries. No exceptions without explicit approval.


## Tasks
- FastAPI app factory, basic routers with mocks, health checks.
- Config with `PDF_ENGINE` (`native|mineru|auto`), MinerU flags.
- Pydantic models for ParsedObject/Section/Spec.
- Store scaffolding, logging, basic tests.

## Phase dependency allowlist

**Allowed (core only):**
- fastapi, uvicorn[standard], pydantic, pydantic-settings, httpx, python-multipart
- SQLAlchemy, sqlmodel (scaffold only)
- charset-normalizer
- pytest (tests)

**Not allowed:** Any parsing/OCR/table/MinerU libs.

