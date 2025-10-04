# Phase P5 — QA, Export & Packaging
**Outcome:** Parity checks, CSV/JSON exports, basic CI wiring.

> **Dependency whitelist (MUST FOLLOW)**
>
> - Python dependencies are allowed **only** if listed in `requirements.txt` (core) or `requirements-optional.txt` (extras).
> - You may not add/import any library that is not listed in one of those files.
> - If a new dependency is needed, STOP and update the requirements files first (subject to review), then proceed.
> - This whitelist is the barrier for adding libraries. No exceptions without explicit approval.


## Tasks
- Parity checks across engines and sampling.
- Export endpoints: CSV/JSON; ensure schema stable.
- Optional pandas-based aggregation if already allowed.

## Phase dependency allowlist

**Allowed additions (only if needed):**
- pandas (and numpy) for CSV/JSON aggregation if not already present from P1.

**Not allowed:** new parsing/OCR libs.

