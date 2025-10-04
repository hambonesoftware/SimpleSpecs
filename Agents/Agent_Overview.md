# Simplespecs Agents — Overview
**Date:** 2025-10-02

> **Dependency whitelist (MUST FOLLOW)**
>
> - Python dependencies are allowed **only** if listed in `requirements.txt` (core) or `requirements-optional.txt` (extras).
> - You may not add/import any library that is not listed in one of those files.
> - If a new dependency is needed, STOP and update the requirements files first (subject to review), then proceed.
> - This whitelist is the barrier for adding libraries. No exceptions without explicit approval.




## Inputs expected by agents
- Plans: `plan/overview.md`, `plan/phase_P{N}_*.md`
- Final stubs: `finalstubs/finalstubs_latest.json`, `finalstubs/finalstubs_P{N}.json`
- Repo root: your working directory should be the project root.

## Hard rules
- Only create/modify files listed for the target phase in `finalstubs_P{N}.json`.
- Preserve exact paths and exported symbols.
- Keep code runnable in a normal Python venv; **no UNO/pyuno**.
- Use mocks only where the phase calls for them.
- **Dependencies:** Only libraries listed in `requirements.txt` or `requirements-optional.txt` may be used.
