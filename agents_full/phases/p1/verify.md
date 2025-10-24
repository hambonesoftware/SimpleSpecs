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
# Ensure fixtures exist for tests
mkdir -p backend/tests/resources
cp "Epf, Co.pdf" backend/tests/resources/sample1.pdf
cp MFC-5M_R2001_E1985.pdf backend/tests/resources/sample2.pdf

export PARSER_MULTI_COLUMN=true HEADERS_SUPPRESS_TOC=true HEADERS_SUPPRESS_RUNNING=true PARSER_ENABLE_OCR=false
pytest -q --maxfail=1 --disable-warnings backend/tests/test_headers_native.py
pytest -q --maxfail=1 --disable-warnings backend/tests/test_mineru_fallback.py

# Manual CLI smoke
python -m backend.cli.parse_headers backend/tests/resources/sample1.pdf --json /tmp/headers1.json --debug
```
Output the report following `_common/verify_report_template.md`.
