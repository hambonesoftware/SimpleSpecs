# SimpleSpecs

SimpleSpecs is an application for parsing engineering specification PDFs and structuring the extracted data for downstream workflow automation.

## Prerequisites
- Python 3.12+
- Node-compatible runtime for serving static frontend (optional during backend-only development)
- Tesseract OCR binary installed and in `PATH` when OCR is required

## Getting Started
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
4. Launch the backend locally:
   ```bash
   ./start_local.sh
   ```
   or on Windows PowerShell:
   ```powershell
   .\start_local.bat
   ```
5. Visit `http://localhost:8000/api/health` to verify the service responds with `{ "ok": true }`.

## Testing
Run the automated test suite with:
```bash
pytest
```

## Project Structure
```
backend/      # FastAPI application
frontend/     # Static HTML/CSS/JS assets
plan/         # Phase plans and reference documents
agents/       # Codex-style execution prompts per phase
```
