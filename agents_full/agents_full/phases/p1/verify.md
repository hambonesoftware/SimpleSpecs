# VERIFY — P1: Parsing & Headers (with MinerU LLM Fallback)

Checklist (PASS/FAIL with evidence)
- Layout parse + multi-column order
- Header detection + level inference
- TOC & running header suppression
- OCR fallback gated (no crash when missing)
- **MinerU fallback present & gated; OpenRouter call mocked in tests; no net by default**
- CLI works; tests & CI green; no API break

Run
```
export PARSER_MULTI_COLUMN=true HEADERS_SUPPRESS_TOC=true HEADERS_SUPPRESS_RUNNING=true PARSER_ENABLE_OCR=false
pytest -q --maxfail=1 --disable-warnings backend/tests/test_headers_native.py
pytest -q --maxfail=1 --disable-warnings backend/tests/test_mineru_fallback.py
```
Output the report following `_common/verify_report_template.md`.
