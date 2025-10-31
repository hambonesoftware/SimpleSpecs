# SimpleSpecs

SimpleSpecs parses engineering specification PDFs and structures the extracted data for downstream workflow automation.

## Local development
1. Create and activate a virtual environment:
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy the environment template and adjust values as needed:
   ```bash
   cp .env.template .env
   ```
4. Launch the backend locally (hot reload enabled):
   ```bash
   ./start_local.sh
   ```
   On Windows PowerShell:
   ```powershell
   .\start_local.bat
   ```
   The helper scripts honour `HOST`, `PORT`, and `LOG_LEVEL` if they are set in your `.env` file.
5. Visit `http://localhost:8000/api/health` to verify the service responds with `{ "ok": true }`.
6. Open `http://localhost:8000/` in your browser to use the SimpleSpecs web app; the FastAPI server serves the static frontend from the same origin.

   If you need to host the static files separately (for example during local prototyping), add a `<meta name="api-base">` tag to `frontend/index.html` or assign `window.API_BASE` at runtime with the full API origin (e.g. `http://127.0.0.1:8000`). The frontend falls back to the same origin when no override is provided.

The server creates the `uploads/` and `exports/` directories on startup if they are missing. Adjust their locations via the `UPLOAD_DIR` and `EXPORT_DIR` environment variables.

### Header extraction configuration

SimpleSpecs sends the full document text to OpenRouter for a high-fidelity outline. Configure behaviour via the following environment variables (also available in `.env.template`):

- `HEADERS_MODE`: keep `llm_full` to enable the OpenRouter pipeline.
- `HEADERS_LLM_MODEL`: fully qualified OpenRouter model identifier (default `anthropic/claude-3.5-sonnet`).
- `HEADERS_LLM_MAX_INPUT_TOKENS`: approximate token budget per request chunk (default `120000`).
- `HEADERS_LLM_TIMEOUT_S`: request timeout in seconds (default `120`).
- `HEADERS_LLM_CACHE_DIR`: on-disk cache for previously processed documents.

The pipeline requires `OPENROUTER_API_KEY`. Cached responses avoid repeated model invocations for unchanged documents.


## Windows single-file bundle (optional)
A PyInstaller spec is provided for packaging the backend as a single executable on Windows.

1. Install build prerequisites in a clean virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt pyinstaller
   ```
2. Generate the bundle:
   ```powershell
   pyinstaller simplespecs.spec
   ```
3. The packaged binary and supporting files are produced in the `dist/SimpleSpecs` directory. Launch `SimpleSpecs.exe` to start the API server (respects the same `.env` settings as the scripts).

## Testing
Run the automated test suite with:
```bash
pytest
```

## Project structure
```
backend/      # FastAPI application
frontend/     # Static HTML/CSS/JS assets
plan/         # Phase plans and reference documents
agents/       # Codex-style execution prompts per phase
```
