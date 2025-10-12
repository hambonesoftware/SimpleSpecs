# Contributing to SimpleSpecs

We welcome contributions! This guide describes the workflow and expectations for
making changes to SimpleSpecs.

## Ground Rules

- Keep the public API stable. Breaking changes to routes or contracts must be
  discussed in an issue before implementation.
- Add tests for all bug fixes and new features. Prefer unit tests over
  integration tests when possible.
- Ensure linting, typing, and tests pass locally before pushing.
- Never commit secrets or real API keys. Use `.env.example` as a reference for
  required configuration.

## Development Workflow

1. **Fork and branch**
   - Fork the repository and clone your fork.
   - Create a feature branch from `main` (e.g., `git checkout -b feature/my-change`).

2. **Bootstrap the environment**
   - Install Python 3.11+ and [uv](https://github.com/astral-sh/uv).
   - Run `make bootstrap` to install dependencies.
   - Copy `.env.example` to `.env` and customize as needed.
   - Install pre-commit hooks with `make precommit-install`.

3. **Make changes**
   - Keep commits focused and descriptive.
   - Follow the existing code style (Black formatting, isort imports, Ruff lint).
   - Update or create documentation alongside code changes when relevant.

4. **Quality gates**
   - Format: `make fmt`
   - Lint: `make lint`
   - Type-check: `make type`
   - Tests: `make test`
   - Coverage (optional but encouraged): `make cov`

5. **Submit a pull request**
   - Push your branch and open a PR against `main`.
   - Fill out the PR template checklist, describing the change and testing
     performed.
   - Ensure GitHub Actions CI is green.

## Reporting Issues

Use GitHub Issues to report bugs or request features. Provide as much context as
possible, including reproduction steps and log output when available.

## Code Review

- Reviews aim to maintain quality and knowledge sharing.
- Expect feedback on design, tests, and style.
- Re-request review after addressing feedback and ensure CI remains green.

Thanks for helping improve SimpleSpecs!
