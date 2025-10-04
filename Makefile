.PHONY: run test lint

run: ## Start the app locally.
uvicorn backend.main:create_app --factory --reload

test: ## Run unit tests.
pytest

lint: ## Run ruff linting.
ruff check .
