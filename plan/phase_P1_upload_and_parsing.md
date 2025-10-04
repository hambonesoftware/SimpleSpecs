# Phase P1 — Upload & Parsing (UNO-less with MinerU option)
**Outcome:** Deterministic extraction to ParsedObject[] using selected engine; DOCX/TXT native; OCR optional.

> **Dependency whitelist (MUST FOLLOW)**
>
> - Python dependencies are allowed **only** if listed in `requirements.txt` (core) or `requirements-optional.txt` (extras).
> - You may not add/import any library that is not listed in one of those files.
> - If a new dependency is needed, STOP and update the requirements files first (subject to review), then proceed.
> - This whitelist is the barrier for adding libraries. No exceptions without explicit approval.


## Tasks
1. POST /ingest: save to `artifacts/{file_id}/source` and register file.
2. NativePdfParser: pdfplumber (text), pikepdf (metadata), PyMuPDF (images), Camelot/Tabula (tables).
3. MinerUPdfParser: call MinerU pipeline and normalize to ParsedObject[].
4. Engine selection: setting or AUTO heuristics.
5. DOCX/TXT extractors.
6. OCR fallback if scanned and MinerU unavailable.
7. GET /parsed/{file_id} returns ParsedObject[].

## Phase dependency allowlist

**Core add-ons permitted in this phase (to parse PDF/DOCX/TXT):**
- PDF (native): pdfplumber, pdfminer.six, PyMuPDF, pikepdf
- DOCX: python-docx, mammoth, docx2python
- TXT: charset-normalizer (already core)

**Optional extras (only if used & system deps available):**
- Tables: camelot-py[base] (Ghostscript), tabula-py (Java), plus pandas, numpy, opencv-python-headless, matplotlib
- OCR fallback: ocrmypdf (Ghostscript + Tesseract), pytesseract
- MinerU client (toggleable): one of magic-pdf **or** mineru

**Not allowed:** PyPDF2/pypdf, regex “parsers”, ad-hoc base64 test assets.

