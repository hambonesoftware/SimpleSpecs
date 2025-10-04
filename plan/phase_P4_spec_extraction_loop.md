# Phase P4 — Spec Extraction Loop
**Outcome:** Loop each granular section → prompt LLM for mechanical specs → collect SpecItem[].

> **Dependency whitelist (MUST FOLLOW)**
>
> - Python dependencies are allowed **only** if listed in `requirements.txt` (core) or `requirements-optional.txt` (extras).
> - You may not add/import any library that is not listed in one of those files.
> - If a new dependency is needed, STOP and update the requirements files first (subject to review), then proceed.
> - This whitelist is the barrier for adding libraries. No exceptions without explicit approval.


## Tasks
- For each section: prompt includes section number/title + text; store results with provenance.
- Aggregate and deduplicate by source objects.
- Return SpecItem[] and expose routes.

## Phase dependency allowlist

**Allowed additions:** none required beyond core + P2 LLM usage.
**Not allowed:** new parsing/ML frameworks.

