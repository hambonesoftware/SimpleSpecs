UV ?= uv
PYTHON_SOURCES = backend scripts tests run.py run_local.py ollama_test.py
MYPY_TARGETS ?= backend/main.py backend/config.py backend/routers/health.py backend/tests/test_health.py

.PHONY: bootstrap fmt lint type test cov precommit-install run

bootstrap: ## Install project dependencies using uv.
	$(UV) sync --dev

fmt: ## Format code with Black and isort.
	$(UV) run black $(PYTHON_SOURCES)
	$(UV) run isort $(PYTHON_SOURCES)

lint: ## Run Ruff lint checks.
	$(UV) run ruff check $(PYTHON_SOURCES)

type: ## Run static type checks with mypy.
	$(UV) run mypy $(MYPY_TARGETS)

test: ## Run the unit test suite.
	$(UV) run pytest

cov: ## Run tests with coverage reporting.
	$(UV) run pytest --cov=backend --cov-report=term-missing

precommit-install: ## Install pre-commit hooks.
	$(UV) run pre-commit install

run: ## Start the FastAPI application locally.
	$(UV) run uvicorn backend.main:create_app --factory --reload
