# PDF Ingestion Test Run — Epf, Co. & MFC-5M Samples

## Context
- Request: verify native parsing flow for the bundled sample PDFs `Epf, Co.pdf` and `MFC-5M_R2001_E1985.pdf`.
- Environment: local pytest execution inside the SimpleSpecs repo.

## Commands Executed
1. `pytest backend/tests/test_parse_epf_pdf.py backend/tests/test_parse_mfc_pdf.py`
   - Purpose: targeted verification that the FastAPI ingest workflow succeeds for both PDFs.
   - Result: both tests passed, confirming successful ingestion, storage, and retrieval of parsed text blocks for each document.
2. `pytest`
   - Purpose: full regression sweep to ensure broader functionality remains stable after running the targeted PDF checks.
   - Result: entire suite passed with existing skips preserved.

## Outcomes
- Both sample PDFs upload and parse without errors using the native engine pathway.
- Re-running the complete test suite verifies no regressions were introduced by exercising these artifacts.

## Next Steps
- None required at this time; monitor routine CI to keep verifying the PDF baselines.
