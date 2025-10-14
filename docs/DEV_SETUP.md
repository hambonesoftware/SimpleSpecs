# Developer Setup

This guide walks through provisioning a local environment for SimpleSpecs from a clean clone.

## Prerequisites

- **Python** 3.11 or 3.12 available on your PATH.
- **uv** package manager (`pip install uv` or download from <https://github.com/astral-sh/uv#installation>).
- (Optional) **Make** utility. On Windows, install via [GnuWin32](http://gnuwin32.sourceforge.net/packages/make.htm) or use `make` from WSL.
- (Optional) Docker Desktop if you prefer containerised services.

### Platform Notes

- **macOS**: Homebrew installs of Python place binaries under `/opt/homebrew/bin`. Ensure this directory is at the front of your PATH.
- **Windows**: Use PowerShell or Git Bash. When using PowerShell, prefix commands with `uvx` as needed or run `pip install uv` inside a virtual environment.
- **Linux**: Package managers may lag on uv releases; installing via `pip install uv` is recommended.

## One-Time Bootstrap

1. Clone the repository and switch to the desired branch.

   ```bash
   git clone https://github.com/hambonesoftware/SimpleSpecs.git
   cd SimpleSpecs
   git checkout phase0-bootstrap
   ```

2. Copy the environment template and adjust values for your stack.

   ```bash
   cp .env.example .env
   ```

3. Install dependencies (runtime + dev) using uv.

   ```bash
   uv sync --dev
   ```

4. Install the pre-commit hooks (runs linting/typing automatically on commit).

   ```bash
   make precommit-install
   ```

## Daily Driver Commands

- **Run formatters**: `make fmt`
- **Run Ruff lint**: `make lint`
- **Type-check**: `make type`
- **Execute tests**: `make test`
- **Coverage report**: `make cov`
- **Start the API (hot reload)**: `make run`

Each command uses `uv run` to execute tools in the synced virtual environment.

## Smoke Test / First Run

After bootstrapping, validate the installation:

```bash
make bootstrap
make test
```

Both commands should succeed without additional configuration (database defaults to a local SQLite file).

## Optional Dependencies

Some PDF/table extraction features rely on heavier packages (Camelot, Tesseract, OCRmyPDF). Install them with extras when needed:

```bash
uv sync --extra optional --dev
```

Follow upstream installation docs for native binaries (e.g., Ghostscript, Tesseract) when enabling these features.

## Native header parser quickstart

The phase 1 parser introduces feature flags that can be toggled via environment
variables (with or without the `SIMPLS_` prefix):

- `PARSER_MULTI_COLUMN` — enable column-aware reading order heuristics (default `true`).
- `HEADERS_SUPPRESS_TOC` — drop table-of-contents pages (default `true`).
- `HEADERS_SUPPRESS_RUNNING` — hide running headers/footers (default `true`).
- `PARSER_ENABLE_OCR` — call Tesseract when a page has little native text (default `false`).
- `PARSER_DEBUG` — write structured JSON debug logs to the standard logger (default `false`).

For rapid iteration run the CLI entry point directly:

```bash
python -m backend.cli.parse_headers path/to/document.pdf --json /tmp/headers.json --debug
```

The CLI respects the same environment variables and prints the resolved flag
values when `--debug` is supplied. For synthetic fixtures, see
`backend/tests/test_headers_native.py`, which constructs deterministic PDFs at
runtime to validate the parser without committing binary assets.
