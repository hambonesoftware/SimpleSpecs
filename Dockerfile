# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ghostscript \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        poppler-utils \
        tesseract-ocr \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

FROM base AS builder
WORKDIR /build

COPY requirements.txt ./

RUN pip install --upgrade pip \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM base AS runtime
WORKDIR /app

ENV PYTHONPATH=/app \
    UPLOAD_DIR=/data/uploads \
    EXPORT_DIR=/data/exports \
    DATABASE_URL=sqlite:////data/db/simplespecs.db \
    HOST=0.0.0.0 \
    PORT=8000 \
    LOG_LEVEL=info

COPY --from=builder /wheels /wheels
COPY requirements.txt ./

RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY backend ./backend
COPY frontend ./frontend
COPY start_local.sh ./start_local.sh
COPY start_local.bat ./start_local.bat
COPY .env.template ./.env.template
COPY .env.production.example ./.env.production.example
COPY docker-entrypoint.sh ./docker-entrypoint.sh

RUN chmod +x docker-entrypoint.sh

VOLUME ["/data/uploads", "/data/exports", "/data/db"]

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
