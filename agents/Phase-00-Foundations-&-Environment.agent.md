# Phase 00 — Foundations & Environment (Agent Prompt)

## ROLE
You are a senior engineer executing this phase for the SimpleSpecs app. Audit first, Patch second. Keep existing public APIs stable.

## INPUTS
- Repository: the SimpleSpecs repo connected in this session.
- Plan reference: the matching phase in `plan.zip`.
- Sample PDFs: `samples/EPF.pdf`, `samples/MFC.pdf` (or as present in repo).

## OBJECTIVES
- Scaffold repo, env, CI, and smoke health endpoint.

## CONSTRAINTS
- Python 3.12 + FastAPI backend; HTML/CSS + ESM-JS frontend.
- Use OpenRouter as primary LLM provider with the provided hardening.
- Maintain strict fenced outputs for LLM responses.
- Respect `.env` feature flags.

## AUDIT (do this before changing anything)
- Confirm presence of `backend/main.py` and `frontend/` skeleton.
- Verify `requirements.txt`, `.env.template`, `README` quickstart.
- Ensure `pytest` config exists (or create).

## PATCH (apply changes if audit gaps exist)
- Create `backend/main.py` with FastAPI app and `GET /api/health`.
- Add `.env.template` with all flags and docstrings.
- Add `start_local.(sh|bat)`; update README with run commands.
- Pin dependencies in `requirements.txt`.

## TESTS
- Add `tests/test_health.py`: assert response is 200 and JSON contains `ok: true`.
- Run pytest; fix import issues.

## ACCEPTANCE CHECKS
- Health endpoint passes; CI green.

## DONE WHEN
- Dev can run `uvicorn backend.main:app` and hit /api/health.
