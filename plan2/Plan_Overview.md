# SimpleSpecs Header Parsing Upgrade — Plan 2 Overview

## Objective
Enhance the SimpleSpecs PDF parsing and header extraction to achieve full hierarchical coverage of all headers and subheaders, maintaining API stability.

## Scope
- Repository: `hambonesoftware/SimpleSpecs`
- Branch: `feat/headers-upgrade`
- Tools: PyMuPDF, pdfplumber, OCR fallback, FastAPI backend
- Deliverables: Multi-column detection, header hierarchy tree, TOC suppression, OCR support, reproducible golden tests.

## Phased Plan Summary

| Phase | Title | Summary | Deliverables |
|-------|--------|----------|---------------|
| P0 | Baseline & Safety Net | Create golden 'before' artifacts, CI replay job | Baseline outputs |
| P1 | Audit & Gap Matrix | Identify missing best practices | Gap matrix |
| P2 | Design & Spikes | Draft architecture, run small proofs | Design doc & spikes |
| P3 | Extraction Core | Build robust reader for layout + OCR | pdf_reader.py |
| P4 | Header Detector & Tree Builder | Build nested header hierarchy | headers_detect.py |
| P5 | Integration & API Parity | Integrate with router, preserve endpoints | API compatibility |
| P6 | Tests & Golden Proofs | Ensure correctness and coverage | Full test suite |
| P7 | Performance & Resilience | Optimize and benchmark | Benchmarks |
| P8 | Docs & Rollout | Final docs, changelog, release | README-headers.md |

## Success Criteria
- Complete hierarchical header tree for both PDFs.
- Deterministic outputs verified by golden tests.
- No API breakage.
