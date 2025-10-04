# Agent — Phase 0: Architecture & Contracts (UNO-less + MinerU toggle)
**Date:** 2025-10-02

> **Dependency whitelist (MUST FOLLOW)**
>
> - Python dependencies are allowed **only** if listed in `requirements.txt` (core) or `requirements-optional.txt` (extras).
> - You may not add/import any library that is not listed in one of those files.
> - If a new dependency is needed, STOP and update the requirements files first (subject to review), then proceed.
> - This whitelist is the barrier for adding libraries. No exceptions without explicit approval.


## Phase dependency allowlist

**Allowed (core only):**
- fastapi, uvicorn[standard], pydantic, pydantic-settings, httpx, python-multipart
- SQLAlchemy, sqlmodel (scaffold only)
- charset-normalizer
- pytest (tests)

**Not allowed:** Any parsing/OCR/table/MinerU libs.


## Read first
- `plan/overview.md`
- `plan/phase_P0_architecture_and_contracts.md`
- `finalstubs/finalstubs_latest.json`
- `finalstubs/finalstubs_P0.json`

## Hard rules
- Only touch files listed for P0.
- Preserve paths/exports.
- No UNO/pyuno.
- **Dependencies:** Only libraries listed in `requirements.txt` or `requirements-optional.txt` may be used.
