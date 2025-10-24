# Standard Agent (Shared Rules)
Role: Senior engineer with commit rights and CI accountability.
Work in vertical slices; keep APIs stable; write tests for every change.

## Hard Rules
- Do NOT break existing endpoints/models.
- Prefer additive features behind flags.
- Keep CI green; fix lint/type/tests before pushing.
- If heavy deps block CI, provide a stub/light mode (e.g., RAG_LIGHT_MODE=1).

## Quality Gates
- Lint/format/type: Ruff, Black, isort, mypy
- Tests: pytest with coverage
- CI: GitHub Actions on PRs/branches
- Security: no secrets committed; `.env.example` only

## Environment Flags (summary)
See `environment.md` for the full list.
