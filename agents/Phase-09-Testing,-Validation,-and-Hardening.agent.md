# Phase 09 — Testing, Validation, and Hardening (Agent Prompt)

## ROLE
You are a senior engineer executing this phase for the SimpleSpecs app. Audit first, Patch second. Keep existing public APIs stable.

## INPUTS
- Repository: the SimpleSpecs repo connected in this session.
- Plan reference: the matching phase in `plan.zip`.
- Sample PDFs: `samples/EPF.pdf`, `samples/MFC.pdf` (or as present in repo).

## OBJECTIVES
- Coverage, security hardening, performance tuning.

## CONSTRAINTS
- Python 3.12 + FastAPI backend; HTML/CSS + ESM-JS frontend.
- Use OpenRouter as primary LLM provider with the provided hardening.
- Maintain strict fenced outputs for LLM responses.
- Respect `.env` feature flags.

## AUDIT (do this before changing anything)
- Coverage report present; golden tests wired.
- Security: upload caps, mimetype/extension checks, path traversal prevention.

## PATCH (apply changes if audit gaps exist)
- Add fuzz cases; large-file tests; concurrency tweaks.
- Improve error messages and logging context (request id).

## TESTS
- Run full pytest; ensure deterministic goldens.
- Load test light concurrency; capture parse/LLM latencies.

## ACCEPTANCE CHECKS
- CI green; coverage meets target; no flakiness over 3 consecutive runs.

## DONE WHEN
- Ready for packaging.
