#!/usr/bin/env bash
set -euo pipefail

HOST_VALUE=${HOST:-0.0.0.0}
PORT_VALUE=${PORT:-8000}
LOG_LEVEL_VALUE=${LOG_LEVEL:-info}

mkdir -p "${UPLOAD_DIR:-/data/uploads}" "${EXPORT_DIR:-/data/exports}"

if [[ -n "${DATABASE_URL:-}" && "${DATABASE_URL}" == sqlite:* ]]; then
  python - <<'PY'
import os
from pathlib import Path

url = os.environ.get("DATABASE_URL") or ""
if url.startswith("sqlite:////"):
    db_path = Path(url.replace("sqlite:////", "/", 1))
elif url.startswith("sqlite:///"):
    db_path = Path(url.replace("sqlite:///", "", 1))
else:
    db_path = None

if db_path is not None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
PY
fi

exec uvicorn backend.main:app --host "${HOST_VALUE}" --port "${PORT_VALUE}" --log-level "${LOG_LEVEL_VALUE}"
