# Agent — Phase 2: Header Discovery (LLM)
**Date:** 2025-10-02

> **Dependency whitelist (MUST FOLLOW)**
>
> - Python dependencies are allowed **only** if listed in `requirements.txt` (core) or `requirements-optional.txt` (extras).
> - You may not add/import any library that is not listed in one of those files.
> - If a new dependency is needed, STOP and update the requirements files first (subject to review), then proceed.
> - This whitelist is the barrier for adding libraries. No exceptions without explicit approval.


## Phase dependency allowlist

**Allowed additions:** none required beyond core (use httpx + LLM endpoints).
**Not allowed:** new parsing/ML frameworks.


## Read first
- `plan/overview.md`
- `plan/phase_P2_header_discovery.md`
- `finalstubs/finalstubs_latest.json`
- `finalstubs/finalstubs_P2.json`

## Hard rules
- Only touch files listed for P2.
- Preserve paths/exports.
- No UNO/pyuno.
- **Dependencies:** Only libraries listed in `requirements.txt` or `requirements-optional.txt` may be used.
