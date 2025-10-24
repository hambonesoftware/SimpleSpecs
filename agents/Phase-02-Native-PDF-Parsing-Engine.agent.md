# Phase 02 — Native PDF Parsing Engine (Agent Prompt)

## ROLE
You are a senior engineer executing this phase for the SimpleSpecs app. Audit first, Patch second. Keep existing public APIs stable.

## INPUTS
- Repository: the SimpleSpecs repo connected in this session.
- Plan reference: the matching phase in `plan.zip`.
- Sample PDFs: `samples/EPF.pdf`, `samples/MFC.pdf` (or as present in repo).

## OBJECTIVES
- Extract robust text blocks with TOC/running-header suppression, OCR/MinerU fallbacks.

## CONSTRAINTS
- Python 3.12 + FastAPI backend; HTML/CSS + ESM-JS frontend.
- Use OpenRouter as primary LLM provider with the provided hardening.
- Maintain strict fenced outputs for LLM responses.
- Respect `.env` feature flags.

## AUDIT (do this before changing anything)
- Verify `services/pdf_native.py` exists; inspect for PyMuPDF usage and multi-column segmentation.
- Confirm OCR and MinerU flags exist and are respected.
- Ensure Camelot detection hooks exist (table region markers).

## PATCH (apply changes if audit gaps exist)
- Build page iterator collecting blocks + bbox + font metrics via PyMuPDF.
- Cross-check lines via pdfplumber; merge with heuristics.
- Implement TOC suppression (keywords + early-page density).
- Implement running header/footer suppression (repeat-region detection).
- Add OCR fallback (pytesseract) if textless pages detected.
- Add MinerU fallback pipeline guarded by `MINERU_FALLBACK`.

## TESTS
- `tests/test_parse_samples.py`: parse EPF/MFC and assert non-empty blocks.
- Snapshot golden parse artifacts if applicable.

## ACCEPTANCE CHECKS
- Both sample PDFs yield stable, non-empty block sets.

## DONE WHEN
- `POST /api/parse/{doc_id}` returns blocks with bbox and fonts.
