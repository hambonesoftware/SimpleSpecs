# Phase P3 — Granular Chunking by Section
**Outcome:** Map ParsedObject[] into section/subsection chunks (one chunk per most-granular section).

> **Dependency whitelist (MUST FOLLOW)**
>
> - Python dependencies are allowed **only** if listed in `requirements.txt` (core) or `requirements-optional.txt` (extras).
> - You may not add/import any library that is not listed in one of those files.
> - If a new dependency is needed, STOP and update the requirements files first (subject to review), then proceed.
> - This whitelist is the barrier for adding libraries. No exceptions without explicit approval.


## Tasks
- Build chunks using the headers tree spans.
- Each chunk contains only its section/subsection content.
- Deterministic ordering & reproducible IDs.

## Phase dependency allowlist

**Allowed additions:** none (pure Python logic).
**Not allowed:** new parsing/ML frameworks.

