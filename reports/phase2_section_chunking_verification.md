# Phase 2 Verification Report (Section-Chunking)

## Summary
Overall: FAIL

## Evidence (commit/PR)
- Branch: phase2-specs-rag @ 26b438f【a0a97d†L1-L1】
- PR: “Phase 2: Spec Atomization & Vector Search (Section-Chunking Mode)” — Status: UNKNOWN (CI: UNKNOWN)

## Checklist Results
A) Section-Chunking Override: PASS — `build_section_chunks` emits exactly one chunk per section node while preserving header paths, and settings hard-enforce `RAG_CHUNK_MODE="section"`; unit tests cover heading exclusion.【F:backend/services/chunker.py†L115-L212】【F:backend/config.py†L50-L67】【F:backend/tests/test_chunker.py†L27-L126】
B) Spec Atomizer: PASS — Atomizer normalizes values/units, classifies into the required taxonomy, and returns confidence; tests assert normalization/classification outcomes.【F:backend/services/spec_atomizer.py†L1-L230】【F:backend/tests/test_atomizer.py†L20-L64】【F:backend/models.py†L222-L253】
C) Embeddings/Index/Search: PASS — Embedding service provides hash-based light mode and optional model loading, index store persists vectors, and hybrid search fuses BM25/dense scores honoring `RAG_HYBRID_ALPHA`; tests validate ranking and persistence.【F:backend/services/embeddings.py†L1-L87】【F:backend/services/index_store.py†L1-L109】【F:backend/services/search.py†L1-L150】【F:backend/tests/test_search.py†L16-L55】
D) APIs (Additive): PASS — `/api/specs` router adds extract/index/search/export endpoints without altering prior routes.【F:backend/app/routers/specs.py†L1-L86】
E) CLI Tools: FAIL — Documentation instructs running `specs_index` against `backend/tests/resources/sample1.pdf`, but no such PDF exists and the command aborts, preventing the documented smoke run; follow-on query also fails.【F:docs/DEV_SETUP.md†L111-L114】【3fee90†L1-L1】【bf49e1†L1-L1】【11c1b5†L1-L1】
F) Config & Docs: PASS — Config exposes the required RAG flags and docs note the section-chunking override plus light/full modes.【F:backend/config.py†L50-L67】【F:README.md†L36-L87】【F:docs/DEV_SETUP.md†L94-L119】
G) Tests & Goldens: FAIL — Required test modules and goldens exist, but the mandate to reuse Phase-1 PDFs under `backend/tests/resources/` is unmet because the directory is absent.【F:backend/tests/test_chunker.py†L27-L126】【F:backend/tests/test_specs_routes.py†L113-L165】【F:backend/tests/golden/sample1_specs.json†L1-L24】【F:backend/tests/golden/sample2_specs.json†L1-L16】【3fee90†L1-L1】
H) Observability: PASS — When `RAG_DEBUG` is enabled the service writes JSONL artifacts and logs fusion components.【F:backend/services/spec_rag.py†L54-L156】【F:backend/services/search.py†L131-L149】【F:README.md†L40-L47】
I) CI Health: FAIL — No evidence of current CI status was available in the offline snapshot; health cannot be confirmed.

## File Diff (vs main)
- Added:
  - backend/app/__init__.py
  - backend/app/routers/__init__.py
  - backend/app/routers/specs.py
  - backend/cli/specs_index.py
  - backend/cli/specs_query.py
  - backend/services/embeddings.py
  - backend/services/index_store.py
  - backend/services/search.py
  - backend/services/spec_atomizer.py
  - backend/services/spec_rag.py
  - backend/tests/golden/sample1_specs.json
  - backend/tests/golden/sample2_specs.json
  - backend/tests/test_atomizer.py
  - backend/tests/test_search.py
  - backend/tests/test_specs_cli.py
  - backend/tests/test_specs_routes.py【fc51ca†L1-L26】
- Modified:
  - README.md
  - backend/config.py
  - backend/main.py
  - backend/models.py
  - backend/services/chunker.py
  - backend/services/specs.py
  - backend/tests/test_chunker.py
  - backend/tests/test_specs_loop_resume.py
  - docs/DEV_SETUP.md【fc51ca†L1-L26】

## Test & Runtime Logs
- pre-commit: FAIL — `pre-commit` command unavailable in environment.【6b4cd9†L1-L1】
- pytest: PASS — Targeted suite succeeded (coverage warning due to missing plugin).【79c7d8†L1-L5】
- Section/Chunk parity check: 3 sections, 3 chunks — PASS.【1ebc68†L1-L3】
- CLI index/query: FAIL — Indexing aborted due to missing sample PDF; query reports missing index.【bf49e1†L1-L1】【11c1b5†L1-L1】

## Gaps Detected & Precise Fixes
1) Item: CLI smoke instructions reference nonexistent sample PDF
   - Evidence: Docs reference `backend/tests/resources/sample1.pdf` but CLI run fails because the file is absent.【F:docs/DEV_SETUP.md†L111-L114】【bf49e1†L1-L1】
   - Fix:
     - File: `backend/tests/resources/sample1.pdf` (and related assets)
     - Action: Commit the Phase-1 sample PDFs (or adjust docs/tests to point at generated fixtures) so `specs_index` can run as documented.
     - Test: Re-run CLI smoke commands and `backend/tests/test_specs_cli.py` to confirm end-to-end success.

2) Item: Phase-1 PDF reuse requirement unmet in tests
   - Evidence: `backend/tests/resources/` directory is missing, contradicting the specification to reuse the Phase-1 PDFs.【3fee90†L1-L1】
   - Fix:
     - Files: `backend/tests/resources/` (new directory plus PDFs)
     - Action: Restore or reference the original Phase-1 PDF assets for regression coverage, updating tests to load them if size permits or documenting an alternative fixture strategy.
     - Test: Execute the documented pytest targets ensuring the assets are exercised.

3) Item: CI health unclear for Phase-0/Phase-2 pipeline
   - Evidence: No CI status artifacts present in repository snapshot.
   - Fix:
     - File: `reports/` or PR description (non-code)
     - Action: Surface CI results (e.g., update PR body or add a status badge/report) to verify lint/type/test coverage remain green.
     - Test: Ensure CI pipelines complete and attach logs or badges accordingly.

4) Item: `pre-commit` tooling absent in environment
   - Evidence: `pre-commit run --all-files` fails because the executable is missing.【6b4cd9†L1-L1】
   - Fix:
     - File: `requirements-dev.txt` or documentation (depending on project conventions)
     - Action: Add installation guidance or package entry for `pre-commit` so contributors can satisfy the verification step.
     - Test: Install dependencies and confirm `pre-commit run --all-files` passes locally.

## Retest Plan (post-fix)
```bash
export RAG_ENABLE=true RAG_CHUNK_MODE=section RAG_LIGHT_MODE=1
pytest -q --maxfail=1 --disable-warnings \
  backend/tests/test_chunker.py backend/tests/test_atomizer.py \
  backend/tests/test_search.py backend/tests/test_specs_routes.py
```

Acceptance Criteria Recap
- One chunk per section (1:1 with header_path), no token/overlap splits.
- Specs extracted and classified with normalized units.
- Hybrid search functional; APIs & CLI operational.
- Offline by default; CI green with RAG_LIGHT_MODE=1.
- Docs clearly document the override.
