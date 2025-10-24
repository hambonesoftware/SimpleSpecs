# Phase 06 — Semantic Comparison & Risk Scoring (Agent Prompt)

## ROLE
You are a senior engineer executing this phase for the SimpleSpecs app. Audit first, Patch second. Keep existing public APIs stable.

## INPUTS
- Repository: the SimpleSpecs repo connected in this session.
- Plan reference: the matching phase in `plan.zip`.
- Sample PDFs: `samples/EPF.pdf`, `samples/MFC.pdf` (or as present in repo).

## OBJECTIVES
- Compute compliance gaps and risk score vs ASME/ISO/IEC baselines.

## CONSTRAINTS
- Python 3.12 + FastAPI backend; HTML/CSS + ESM-JS frontend.
- Use OpenRouter as primary LLM provider with the provided hardening.
- Maintain strict fenced outputs for LLM responses.
- Respect `.env` feature flags.

## AUDIT (do this before changing anything)
- Check `services/spec_compare.py` for embeddings + rule gates.
- Verify `/api/specs/compare/{doc_id}` and red-team compliance call.

## PATCH (apply changes if audit gaps exist)
- Build baseline vectors; compute similarity; flag missing mandatory clauses.
- Call LLM with compliance prompt → fenced `#compliance#` JSON.
- Aggregate into `risk_report.json` with per-section flags.

## TESTS
- Remove known mandatory sections in a fixture and assert detection ≥ 95%.
- Threshold calibration tests to prevent over-flagging.

## ACCEPTANCE CHECKS
- Simulated removals detected ≥ 95%.

## DONE WHEN
- UI risk panel shows score and missing sections list.
