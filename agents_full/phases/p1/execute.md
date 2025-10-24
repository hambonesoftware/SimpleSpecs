# EXECUTE — P1: Parsing & Headers (with MinerU LLM Fallback)

Branch: p1-headers
Non-negotiables: **API unchanged**.

Repo Fixtures
- Use the two PDFs at repo root as test resources:
  - `Epf, Co.pdf`
  - `MFC-5M_R2001_E1985.pdf`
- Copy them into test resources with stable names:
  ```bash
  mkdir -p backend/tests/resources
  cp "Epf, Co.pdf" backend/tests/resources/sample1.pdf
  cp MFC-5M_R2001_E1985.pdf backend/tests/resources/sample2.pdf
  ```

Deliverables
1) Layout-Aware Native Parsing
   - `backend/services/pdf_native.py` (PyMuPDF spans/blocks; bbox, font, flags)
   - Multi-column reading order; TOC + running header/footer suppression
2) Header Detection
   - `backend/services/headers_detect.py` (numeric/roman/alpha; typography scoring; level inference)
3) OCR Fallback (gated)
   - `PARSER_ENABLE_OCR` flag; soft-fail if Tesseract missing
4) **MinerU-Style LLM Fallback (OpenRouter, gated)**
   - Config: `LLM_FALLBACK_*` and `OPENROUTER_*` in `backend/config.py` and `.env.example`
   - Module: `backend/services/mineru_fallback.py` that uses the **same** OpenRouter pattern you already use
   - Pipeline hook: if native+OCR fail and fallback enabled, call MinerU; expect strict JSON → map to `HeaderItem[]`
   - Tests: mock OpenRouter call; skip live calls unless `ONLINE_TESTS=1`
5) CLI
   - `backend/cli/parse_headers.py` dumps header JSON
6) Tests & Goldens
   - `backend/tests/test_headers_native.py` (+ goldens) proving hierarchy, suppression, mixed numbering
   - `backend/tests/test_mineru_fallback.py` proving JSON mapping & gating

Acceptance
- Complete hierarchical header trees; TOC/running headers excluded
- **LLM fallback** is gated, uses OpenRouter exactly as configured, and has mocked tests
- CLI prints JSON; tests & CI pass; **no public API changes**
