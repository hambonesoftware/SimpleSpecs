# Phase 03 — Header & Subheader Extraction (LLM + Rules) (Agent Prompt)

## ROLE
You are a senior engineer executing this phase for the SimpleSpecs app. Audit first, Patch second. Keep existing public APIs stable.

## INPUTS
- Repository: the SimpleSpecs repo connected in this session.
- Plan reference: the matching phase in `plan.zip`.
- Sample PDFs: `samples/EPF.pdf`, `samples/MFC.pdf` (or as present in repo).

## OBJECTIVES
- Produce complete hierarchical outline, fenced as `#headers#` and JSON.

## CONSTRAINTS
- Python 3.12 + FastAPI backend; HTML/CSS + ESM-JS frontend.
- Use OpenRouter as primary LLM provider with the provided hardening.
- Maintain strict fenced outputs for LLM responses.
- Respect `.env` feature flags.

## AUDIT (do this before changing anything)
- Check `_headers_common.py` for regex of numeric/alpha/roman headers.
- Confirm TOC exclusion and font-size/weight scoring.
- Confirm `/api/headers/{doc_id}` exists and calls OpenRouter.

## PATCH (apply changes if audit gaps exist)
- Build candidate header list with regex + font/indent heuristics.
- Call OpenRouter with the Headers prompt; require fenced output.
- Validate fences and fallback to regex-only if LLM fails.
- Persist outline JSON and fenced text; expose diff viewer in UI.

## TESTS
- `tests/test_headers_golden.py`: compare EPF/MFC outlines to goldens.
- Negative test: ensure TOC lines are excluded.

## ACCEPTANCE CHECKS
- Header recall ≥ 0.99 on EPF/MFC goldens.

## DONE WHEN
- Collapsible outline visible in UI; API returns fenced + JSON.
