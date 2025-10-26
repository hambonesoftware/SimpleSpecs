# SimpleSpecs — Development Plan
_Last updated: 2025-10-24 00:58_

This archive provides a **complete, actionable build plan** for your SimpleSpecs-style application:
- **Backend:** Python 3.12, FastAPI, SQLModel/SQLite, PyMuPDF, pdfplumber, Camelot, pytesseract (OCR), optional MinerU (fallback)
- **Frontend:** HTML, CSS, ESM‑JS (no framework)
- **LLM:** OpenRouter (primary) + optional Ollama fallback
- **Goal:** Parse customer PDFs, extract **full header trees** and **departmental specifications** hardened by **ASME/ISO** terms, produce exports, and track compliance/risk.

## What’s inside
- `plan/Phase-00-Foundations.md` through `plan/Phase-13-Operational-Readiness-&-Runbooks.md` — **one file per phase** with objectives, tasks, prompts, endpoints, checklists, and exit criteria.
- `plan/Standards-ASME-ISO.md` — the standards hardening reference used throughout.
- `plan/Prompts-Library.md` — canonical LLM prompts (headers, classification, red-team checks).
- `plan/Testing-Strategy.md` — consolidated test plan across phases.
- `plan/Config-Toggles.md` — environment variables and behavior toggles.
- `plan/Glossary.md` — canonical terms used in plans.
- `plan/File-Tree.md` — target repository layout.

## How to use this plan
1. **Start at Phase 00**, complete tasks top-to-bottom. Each phase lists **Dependencies** and **Exit/Acceptance Criteria** — do not proceed until they pass.
2. Use **Prompts-Library.md** wherever a phase requires LLM involvement. Keep outputs fenced and machine‑readable.
3. Maintain **feature flags** in `.env` as outlined in `plan/Config-Toggles.md` to switch providers (OpenRouter/Ollama) and parsing modes (native/OCR/MinerU).
4. Follow **Testing-Strategy.md** at the end of each phase; commit golden outputs for the EPF/MFC sample PDFs.
5. When in doubt, search for the relevant keyword in the plan folder (e.g., “TOC suppression”, “max_tokens hardening”, “ASME Y14 gate”).

## Success criteria (end-to-end)
- Upload → Parse → Headers → Specs (Mech/Elect/Controls/Software/PM) → Risk/Compliance → Approve → Export
- **Header completeness** ≥ 99% on sample PDFs; **departmental precision/recall** targets specified in Testing-Strategy.
- All endpoints stable; frontend is responsive, local-first; OpenRouter usage adheres to policy; fallbacks work offline.
