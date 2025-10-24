# Phase 10 — Deployment & Packaging (Agent Prompt)

## ROLE
You are a senior engineer executing this phase for the SimpleSpecs app. Audit first, Patch second. Keep existing public APIs stable.

## INPUTS
- Repository: the SimpleSpecs repo connected in this session.
- Plan reference: the matching phase in `plan.zip`.
- Sample PDFs: `samples/EPF.pdf`, `samples/MFC.pdf` (or as present in repo).

## OBJECTIVES
- Docker/compose and optional Windows EXE; final docs.

## CONSTRAINTS
- Python 3.12 + FastAPI backend; HTML/CSS + ESM-JS frontend.
- Use OpenRouter as primary LLM provider with the provided hardening.
- Maintain strict fenced outputs for LLM responses.
- Respect `.env` feature flags.

## AUDIT (do this before changing anything)
- Dockerfile present; static `frontend/` mounted by FastAPI; health endpoints.
- Secrets injection for `OPENROUTER_API_KEY`.

## PATCH (apply changes if audit gaps exist)
- Create multi-stage Dockerfile and compose with volumes for uploads/exports.
- Add PyInstaller spec (optional) for Windows bundle.
- Final README with backup/upgrade procedures.

## TESTS
- `docker compose up` smoke: health 200; full flow on samples.
- Windows EXE smoke (optional).

## ACCEPTANCE CHECKS
- Cold start < 3s (dev); docs complete.

## DONE WHEN
- Ops can run with one command and rotate secrets.
