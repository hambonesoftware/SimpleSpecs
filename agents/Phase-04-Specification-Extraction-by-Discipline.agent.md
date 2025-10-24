# Phase 04 — Specification Extraction by Discipline (Agent Prompt)

## ROLE
You are a senior engineer executing this phase for the SimpleSpecs app. Audit first, Patch second. Keep existing public APIs stable.

## INPUTS
- Repository: the SimpleSpecs repo connected in this session.
- Plan reference: the matching phase in `plan.zip`.
- Sample PDFs: `samples/EPF.pdf`, `samples/MFC.pdf` (or as present in repo).

## OBJECTIVES
- Extract atomic spec lines and classify by department with ASME/ISO priors.

## CONSTRAINTS
- Python 3.12 + FastAPI backend; HTML/CSS + ESM-JS frontend.
- Use OpenRouter as primary LLM provider with the provided hardening.
- Maintain strict fenced outputs for LLM responses.
- Respect `.env` feature flags.

## AUDIT (do this before changing anything)
- Verify `services/spec_extraction.py` exists with term lexicons in `resources/terms/`.
- Confirm `/api/specs/extract/{doc_id}` endpoint and department buckets.

## PATCH (apply changes if audit gaps exist)
- Segment blocks under headers into atomic lines.
- Rule-pass with term lexicons; LLM-pass for ambiguous lines → fenced `#classes#` JSON.
- Attach provenance (header ids/paths) to each line.

## TESTS
- `tests/test_specs_classify.py`: precision/recall ≥ baseline on samples.
- Edge-case tests for cross-discipline phrases.

## ACCEPTANCE CHECKS
- F1 ≥ 0.90 on samples; Unknown bucket only for true ambiguities.

## DONE WHEN
- UI tabs show per-discipline buckets with download buttons.
