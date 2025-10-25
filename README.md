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

## Running with Docker
1. Copy the production environment example and update secrets:
   ```bash
   cp .env.production.example .env
   ```
2. Build the runtime image:
   ```bash
   docker build -t simplespecs:latest .
   ```
3. Start the full stack with Docker Compose:
   ```bash
   docker compose up
   ```
   The compose file provisions persistent named volumes for uploads, exports, and the SQLite database. To override the published port or storage locations, set `PORT`, `UPLOAD_DIR`, or `EXPORT_DIR` in the `.env` file before launching.
4. Rotate secrets by updating `.env` (for example, the `OPENROUTER_API_KEY`) and restarting the service:
   ```bash
   docker compose down
   docker compose up -d
   ```

## Operations handbook
- **Cold start**: a fresh container starts in under three seconds on a typical developer laptop. The `docker-entrypoint.sh` script prepares storage directories automatically.
- **Backups**: snapshot or copy the `uploads`, `exports`, and `db` volumes. With Docker Desktop:
  ```bash
  docker compose down
  docker run --rm -v simplespecs_uploads:/data alpine tar czf - -C /data . > uploads-backup.tgz
  docker run --rm -v simplespecs_exports:/data alpine tar czf - -C /data . > exports-backup.tgz
  docker run --rm -v simplespecs_db:/data alpine tar czf - -C /data . > db-backup.tgz
  ```
  Restore by reversing the process (`tar xzf` into the mounted volume) before bringing the stack back up.
- **Upgrades**: rebuild the image after pulling changes and apply database migrations if required (current schema auto-creates):
  ```bash
  git pull
  docker compose build
  docker compose up -d
  ```
- **Non-Docker fallback**: the `start_local.sh` and `start_local.bat` scripts remain available for bare-metal installs when Docker is not an option.

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
