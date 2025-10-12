# Agents2 — Orchestrated Agent Suite for SimpleSpecs Header Upgrade

This package defines an **overview agent** and **phase-specific agents** (P0–P8). Each agent file is a drop-in system prompt
you can paste into your orchestration tool (ChatGPT, OpenRouter, CrewAI, LangGraph, etc.).

## Global Principles
- **Do not break public APIs.** Keep `/api/headers` contract stable.
- **Audit → Patch → Prove.** Always confirm missing practices before adding new ones.
- **Determinism.** Same inputs produce the same header trees.
- **Traceability.** Every decision has an artifact or log.
- **Small, reviewable PRs.** One cohesive concern per PR.

## Files
- `Agent_P0_Baseline.md` through `Agent_P8_Docs_Rollout.md` — Operational prompts per phase.
- Each agent includes: **Role**, **Objectives**, **Inputs**, **Tools**, **Constraints**, **Step Plan**, **Artifacts**, **Self‑Checks**, **Git & CI Guidance**, and **Hand‑off Notes**.

## Handoff Order
P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7 → P8

## Shared Inputs (for all agents)
- Repo: `hambonesoftware/SimpleSpecs` (branching off `feat/headers-upgrade`)
- Two sample PDFs (for goldens)
- Python 3.12, FastAPI backend, PyMuPDF/pdfplumber, optional OCR (tesseract or equivalent)

## Shared Outputs
- Reproducible artifacts in `tests/golden/`, `tests/fixtures/`, and `docs/`
- CI passing: lint, type-check, unit, E2E
- Tagged release at the end (P8)
