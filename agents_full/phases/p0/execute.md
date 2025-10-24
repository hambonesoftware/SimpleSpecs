# EXECUTE — P0: Bootstrap & Governance
Branch: p0-bootstrap
Goal: Reproducible dev env, CI, CORS, smoke tests, governance docs. **No API changes.**

Deliverables
- pyproject.toml (Ruff/Black/isort/mypy), pytest.ini, .pre-commit-config.yaml
- Makefile (fmt/lint/type/test/cov/run), .env.example, docs/DEV_SETUP.md
- .github/workflows/ci.yml, .github/dependabot.yml, .github/pull_request_template.md
- CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, CODEOWNERS
- backend/tests/test_health.py and a non-breaking /health route
- CORS reads ALLOW_ORIGINS

Acceptance
- Fresh clone: `make bootstrap && make test` passes
- CI green; no API changes; CORS env honored
