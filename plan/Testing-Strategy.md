# Testing Strategy

## Test layers
1. **Unit Tests (pytest)**: services (files, pdf_native, headers, spec_extraction, llm).
2. **Golden Tests**: Run on EPF and MFC sample PDFs; snapshot headers/spec JSON.
3. **Integration Tests**: Endpoints with mocked LLM provider.
4. **E2E Smoke**: Upload → Extract → Approve → Export through UI.
5. **Performance**: Parse time per page, tokens per call, concurrency.

## Targets
- Header recall ≥ 0.99 on samples.
- Classification F1 ≥ 0.90 across departments.
- Risk checker detects ≥ 95% of intentionally removed mandatory sections.

## Golden Workflow
- Commit `backend/tests/golden/*.json` from known-good outputs.
- Tests must fail if regressions exceed tolerance.
