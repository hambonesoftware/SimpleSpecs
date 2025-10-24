# Phase 08 — Persistence, Reports, and Export (Agent Prompt)

## ROLE
You are a senior engineer executing this phase for the SimpleSpecs app. Audit first, Patch second. Keep existing public APIs stable.

## INPUTS
- Repository: the SimpleSpecs repo connected in this session.
- Plan reference: the matching phase in `plan.zip`.
- Sample PDFs: `samples/EPF.pdf`, `samples/MFC.pdf` (or as present in repo).

## OBJECTIVES
- Approvals, audit trail, and CSV/DOCX exports.

## CONSTRAINTS
- Python 3.12 + FastAPI backend; HTML/CSS + ESM-JS frontend.
- Use OpenRouter as primary LLM provider with the provided hardening.
- Maintain strict fenced outputs for LLM responses.
- Respect `.env` feature flags.

## AUDIT (do this before changing anything)
- Verify `models/spec_record.py` and approve/freeze flow.
- Check export endpoints and file retention behaviour.

## PATCH (apply changes if audit gaps exist)
- Implement approve transition with content hash.
- Implement CSV per department and DOCX with header hierarchy.
- Add audit logging for actions.

## TESTS
- Approve twice should be idempotent; hash stays stable.
- Export smoke tests: CSV row counts; DOCX headers present.

## ACCEPTANCE CHECKS
- Hash-stable exports; audit entries recorded.

## DONE WHEN
- UI can approve and download exports.
