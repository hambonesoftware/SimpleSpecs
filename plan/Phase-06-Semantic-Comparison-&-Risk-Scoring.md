# Phase 06 — Semantic Comparison & Risk Scoring

## Objectives
- Compare extracted specs to baselines; compute risk/compliance scores.

## Scope
- Embedding-based similarity + rule-based gates for mandatory sections.

## Architecture/Stack
- Backend: Python 3.12, FastAPI, SQLModel/SQLite
- PDF: PyMuPDF, pdfplumber, Camelot; pytesseract OCR; optional MinerU fallback
- LLM: OpenRouter primary; Ollama optional fallback
- Frontend: HTML/CSS + ESM‑JS

## Dependencies
- Phases 03/04 outputs.

## Tasks
- Build baseline term sets per standard family and department.
- Generate embeddings (local small model or sentence-transformers).
- Similarity matrix between extracted lines and baselines; threshold to flag gaps.
- Red-team compliance prompt to list missing sections (fenced JSON).
- Aggregate to risk score (0–1) and annotate specs with flags.

## API Endpoints (new/changed)
- `POST /api/specs/compare/{doc_id}` → risk score + missing items.

## Config & Flags
- Model path, threshold values, toggles for red-team call.

## Prompts (if applicable)
- Red-Team Consistency (from Prompts-Library.md).

## Artifacts & Deliverables
- `risk_report.json` with per-section scoring and missing list.

## Acceptance Criteria / Exit Gates
- Detect ≥ 95% of simulated removals in tests.

## Risks & Mitigations
- Over-flagging; calibrate with holdout set and allow user overrides.

## Rollback
- Disable red-team step; show rule-based diffs only.
