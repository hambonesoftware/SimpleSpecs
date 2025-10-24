# Phase 07 — Frontend Modernization (ESM-JS UI) (Agent Prompt)

## ROLE
You are a senior engineer executing this phase for the SimpleSpecs app. Audit first, Patch second. Keep existing public APIs stable.

## INPUTS
- Repository: the SimpleSpecs repo connected in this session.
- Plan reference: the matching phase in `plan.zip`.
- Sample PDFs: `samples/EPF.pdf`, `samples/MFC.pdf` (or as present in repo).

## OBJECTIVES
- Build responsive UI with upload → parse → headers → specs → risk flow.

## CONSTRAINTS
- Python 3.12 + FastAPI backend; HTML/CSS + ESM-JS frontend.
- Use OpenRouter as primary LLM provider with the provided hardening.
- Maintain strict fenced outputs for LLM responses.
- Respect `.env` feature flags.

## AUDIT (do this before changing anything)
- Inspect `frontend/index.html`, `css/`, `js/api.js`, `js/ui.js` for modular ESM imports.
- Verify a11y basics and error states.

## PATCH (apply changes if audit gaps exist)
- Implement panels and nav; spinners/toasts; collapsible trees.
- Add export buttons (CSV/JSON/DOCX endpoints).

## TESTS
- Manual smoke: upload and full pipeline on EPF/MFC.
- Optional DOM tests via Jest + jsdom.

## ACCEPTANCE CHECKS
- All flows work without refresh; graceful error handling.

## DONE WHEN
- Stakeholder demoable UI with dark-mode basics.
