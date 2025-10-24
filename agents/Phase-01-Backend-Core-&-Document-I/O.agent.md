# Phase 01 — Backend Core & Document I/O (Agent Prompt)

## ROLE
You are a senior engineer executing this phase for the SimpleSpecs app. Audit first, Patch second. Keep existing public APIs stable.

## INPUTS
- Repository: the SimpleSpecs repo connected in this session.
- Plan reference: the matching phase in `plan.zip`.
- Sample PDFs: `samples/EPF.pdf`, `samples/MFC.pdf` (or as present in repo).

## OBJECTIVES
- Implement upload/list endpoints and document model.

## CONSTRAINTS
- Python 3.12 + FastAPI backend; HTML/CSS + ESM-JS frontend.
- Use OpenRouter as primary LLM provider with the provided hardening.
- Maintain strict fenced outputs for LLM responses.
- Respect `.env` feature flags.

## AUDIT (do this before changing anything)
- Check for `models/document.py`, `routers/files.py`, `services/files.py`.
- Confirm upload storage path and checksum/dedup logic.

## PATCH (apply changes if audit gaps exist)
- Implement `Document` (SQLModel): id, filename, checksum, uploaded_at, status.
- Implement `POST /api/upload` and `GET /api/files` with streaming upload and mimetype checks.
- Add frontend drag-and-drop uploader with progress and table listing.

## TESTS
- `tests/test_upload.py`: small PDF upload; duplicate upload deduped by checksum.
- Large file mock to verify size cap handling.

## ACCEPTANCE CHECKS
- Can upload/list PDFs; duplicates deduped.

## DONE WHEN
- Files appear in DB and on disk under `upload_objects_path/<doc_id>/`.
