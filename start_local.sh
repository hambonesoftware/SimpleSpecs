#!/usr/bin/env bash
set -euo pipefail

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

HOST_VALUE=${HOST:-0.0.0.0}
PORT_VALUE=${PORT:-8000}
LOG_LEVEL_VALUE=${LOG_LEVEL:-info}

exec uvicorn backend.main:app \
  --host "${HOST_VALUE}" \
  --port "${PORT_VALUE}" \
  --log-level "${LOG_LEVEL_VALUE}" \
  --reload
