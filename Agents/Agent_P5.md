# Agent — Phase 5: QA, Export & Packaging
**Date:** 2025-10-02

> **Dependency whitelist (MUST FOLLOW)**
>
> - Python dependencies are allowed **only** if listed in `requirements.txt` (core) or `requirements-optional.txt` (extras).
> - You may not add/import any library that is not listed in one of those files.
> - If a new dependency is needed, STOP and update the requirements files first (subject to review), then proceed.
> - This whitelist is the barrier for adding libraries. No exceptions without explicit approval.


## Phase dependency allowlist

**Allowed additions (only if needed):**
- pandas (and numpy) for CSV/JSON aggregation if not already present from P1.

**Not allowed:** new parsing/OCR libs.


## Read first
- `plan/overview.md`
- `plan/phase_P5_QA_export_and_packaging.md`
- `finalstubs/finalstubs_latest.json`
- `finalstubs/finalstubs_P5.json`

## Hard rules
- Only touch files listed for P5.
- Preserve paths/exports.
- No UNO/pyuno.
- **Dependencies:** Only libraries listed in `requirements.txt` or `requirements-optional.txt` may be used.
