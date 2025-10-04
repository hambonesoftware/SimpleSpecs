# Agent — Phase 1: Upload & Parsing (Native + MinerU)
**Date:** 2025-10-02

> **Dependency whitelist (MUST FOLLOW)**
>
> - Python dependencies are allowed **only** if listed in `requirements.txt` (core) or `requirements-optional.txt` (extras).
> - You may not add/import any library that is not listed in one of those files.
> - If a new dependency is needed, STOP and update the requirements files first (subject to review), then proceed.
> - This whitelist is the barrier for adding libraries. No exceptions without explicit approval.


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


## Read first
- `plan/overview.md`
- `plan/phase_P1_upload_and_parsing.md`
- `finalstubs/finalstubs_latest.json`
- `finalstubs/finalstubs_P1.json`

## Hard rules
- Only touch files listed for P1.
- Preserve paths/exports.
- No UNO/pyuno.
- **Dependencies:** Only libraries listed in `requirements.txt` or `requirements-optional.txt` may be used.
