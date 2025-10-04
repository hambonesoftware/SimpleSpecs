# Simplespecs — UNO-less Text Extraction Plan (with MinerU toggle)
**Date:** 2025-10-02

> **Dependency whitelist (MUST FOLLOW)**
>
> - Python dependencies are allowed **only** if listed in `requirements.txt` (core) or `requirements-optional.txt` (extras).
> - You may not add/import any library that is not listed in one of those files.
> - If a new dependency is needed, STOP and update the requirements files first (subject to review), then proceed.
> - This whitelist is the barrier for adding libraries. No exceptions without explicit approval.


This plan removes any dependency on LibreOffice/UNO/pyuno and adopts a native parsing stack for PDF/DOCX/TXT, with a MinerU toggle (Native | MinerU | Auto).

## Goals
- Upload → Parse (text/tables/images + metadata) → LLM Header Discovery → Section Chunking → Per-Section Spec Extraction → Aggregation/Export.
- Keep everything venv-installable via requirements files listed above.
- User-toggleable PDF engine: `native` / `mineru` / `auto`.

## API Surface (high-level)
- POST /ingest → {file_id}
- GET /parsed/{file_id} → ParsedObject[]
- LLM and chunking/specs/export routes in later phases.
