# Phase 1 Verification Report

## Summary
Overall: FAIL

## Evidence (commit/PR)
- Branch: phase1-parse-headers @ 40081a6
- PR: “Phase 1: Parsing & Headers Upgrade (Implement & Prove)” — Status: UNKNOWN (CI: UNKNOWN)

## Checklist Results
A. Layout-aware native parsing: PASS (PyMuPDF spans harvested into structured `TextLine` objects with column clustering heuristics.)
B. Header detection & tree: PASS (Regex numerals/roman/alpha parsing, typography scoring, hierarchical tree building, TOC/running-line suppression.)
C. OCR fallback: PASS (Optional Tesseract integration gated via `PARSER_ENABLE_OCR`, warning-only when missing.)
D. Integration & API stability: FAIL (FastAPI router still proxies to OpenRouter LLM flow; native pipeline never invoked.)
E. Config & docs: PASS (New parser flags wired through settings and documented in README/DEV setup.)
F. CLI tool: FAIL (CLI exists, but sample PDFs referenced in workflow are missing; `python -m backend.cli.parse_headers backend/tests/resources/sample*.pdf` raises FileNotFoundError.)
G. Tests & goldens: FAIL (Golden JSONs exist and tests synthesize PDFs, yet repository lacks the promised `backend/tests/resources/` PDFs.)
H. Observability: PASS (Structured debug logging toggled via `PARSER_DEBUG` spans column clustering and header scoring.)
I. CI health: FAIL (No PR status or CI artifacts available for verification.)

## File Diff (vs main)
- Added:
  - backend/cli/parse_headers.py
  - backend/services/document_pipeline.py
  - backend/services/headers_detect.py
  - backend/services/ocr.py
  - backend/tests/golden/sample1_headers.json
  - backend/tests/golden/sample2_headers.json
  - backend/tests/test_headers_native.py
- Modified:
  - README.md
  - backend/config.py
  - backend/services/headers.py
  - backend/services/pdf_native.py
  - docs/DEV_SETUP.md
- Removed (if any):
  - (none)

## Test & Runtime Logs
- pre-commit: FAIL (`pre-commit` command not installed in sandbox; proxy blocks pip install)
- pytest: PASS (`pytest -q --maxfail=1 --disable-warnings --cov=backend --cov-report=term-missing backend/tests/test_headers_native.py`)
- Coverage: n/a (pytest-cov not installed; summary unavailable)
- CLI sample1: FAIL (`python -m backend.cli.parse_headers backend/tests/resources/sample1.pdf --json /tmp/headers1.json --debug` → FileNotFoundError)
- CLI sample2: FAIL (`python -m backend.cli.parse_headers backend/tests/resources/sample2.pdf --json /tmp/headers2.json --debug` → FileNotFoundError)

## Golden Drift (if any)
- sample1: Not re-generated (CLI run blocked by missing sample PDF). Unit test confirms JSON parity with committed golden.
- sample2: Not re-generated (CLI run blocked by missing sample PDF). Unit test confirms JSON parity with committed golden.

## **Gaps Detected & How to Fix**
1) Item: Router never exercises native pipeline
   - Evidence: `/api/openrouter/headers` handler still posts to OpenRouter and calls `parse_and_store_headers` on the LLM response.
   - Fix:
     - File: `backend/routers/headers.py`
     - Action: Import `run_header_pipeline`, locate uploaded PDF (reuse logic from `backend/services/headers.py::run_header_discovery`), and when native artifacts exist return the pipeline’s `HeaderItem` list without invoking OpenRouter. Persist results via `persist_headers` to keep API behavior identical. Guard behind settings flag so public contract stays stable.

2) Item: CLI workflow references non-existent fixture PDFs
   - Evidence: `backend/tests/resources/sample1.pdf` and `sample2.pdf` are not committed, so the CLI quickstart command fails.
   - Fix:
     - File: Add deterministic fixtures under `backend/tests/resources/` (e.g., export the synthetic PDFs generated in `test_headers_native.py`). Commit them with matching goldens so CLI examples succeed.

3) Item: Tests checklist requirement unmet
   - Evidence: Phase spec explicitly calls for two PDFs in `backend/tests/resources/`, yet repo ships none (tests generate temp PDFs instead).
   - Fix:
     - File: Place the committed PDFs under `backend/tests/resources/` and update `test_headers_native.py` to load those assets instead of synthesizing at runtime. Adjust golden regeneration logic accordingly.

4) Item: CI status unknown
   - Evidence: No GitHub Actions run or badge included; cannot confirm green CI for PR.
   - Fix:
     - Action: Ensure PR references actual GitHub workflow results. Attach CI summary (lint/type/test/coverage) in PR description or include badge/log artifacts for audit trail.

## Retest Plan (post-fix)
```bash
pre-commit run --all-files
pytest -q --maxfail=1 --disable-warnings --cov=backend --cov-report=term-missing
python -m backend.cli.parse_headers backend/tests/resources/sample1.pdf --json /tmp/headers1_fixed.json --debug
python -m backend.cli.parse_headers backend/tests/resources/sample2.pdf --json /tmp/headers2_fixed.json --debug
```

## Acceptance Criteria Recap

* Complete hierarchical trees (numeric/alpha/roman) with correct nesting.
* TOC and running headers **not present**.
* Multi-column reading order correct when enabled.
* API unchanged; CI green; tests pass locally.
