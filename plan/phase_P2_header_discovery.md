# Phase P2 — Header Discovery (LLM)
**Outcome:** Button triggers LLM on full text → nested headers tree (SectionNode).

> **Dependency whitelist (MUST FOLLOW)**
>
> - Python dependencies are allowed **only** if listed in `requirements.txt` (core) or `requirements-optional.txt` (extras).
> - You may not add/import any library that is not listed in one of those files.
> - If a new dependency is needed, STOP and update the requirements files first (subject to review), then proceed.
> - This whitelist is the barrier for adding libraries. No exceptions without explicit approval.


## Tasks
- POST /headers/{file_id}/find: call chosen LLM endpoint; parse nested headers.
- GET /headers/{file_id}: retrieve cached tree.
- Deterministic parsing and idempotency.

## Phase dependency allowlist

**Allowed additions:** none required beyond core (use httpx + LLM endpoints).
**Not allowed:** new parsing/ML frameworks.

