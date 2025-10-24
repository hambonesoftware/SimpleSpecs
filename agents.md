# Agents Pack — SimpleSpecs (Codex-Style)
_Last updated: 2025-10-24 01:01

This pack mirrors the **plan.zip** phases and provides **execution-ready agent prompts** for ChatGPT/Codex-style sessions.
Each agent file is a single prompt you can paste (or ask the GitHub-connected agent to read and execute).

## How to use
1. Ensure the SimpleSpecs repo is available to your session (e.g., via GitHub connector) and your two sample PDFs exist in the repo (e.g., `samples/EPF.pdf`, `samples/MFC.pdf`).
2. Start with **Phase 00** and proceed in order. For each phase:
   - Say: "Read `agents/Phase-XX-*.agent.md` and execute all steps."
   - The agent will edit files, add tests, and run checks per the script.
3. Keep `.env` variables in sync (see below). Use stub keys when testing with mocked LLMs.
4. Accept or reject changes explicitly. When satisfied, commit and proceed.

## Environment & Flags
```
OPENROUTER_API_KEY=
LLM_PROVIDER=openrouter          # or 'ollama'
PARSER_MULTI_COLUMN=true
PARSER_ENABLE_OCR=true
HEADERS_SUPPRESS_TOC=true
HEADERS_SUPPRESS_RUNNING=true
MINERU_FALLBACK=true
DB_URL=sqlite:///./simplespecs.db
```

## LLM Request Hardening
Use this exact logic in the OpenRouter client:
```python
bigger = dict(params or {})
bigger["max_tokens"] = max(_extract_max_tokens(params) or 2048, 4096)

if params:
    referer = params.get("http_referer") or params.get("HTTP-Referer")
    if isinstance(referer, str) and referer.strip():
        headers["HTTP-Referer"] = referer.strip()
    x_title = params.get("x_title") or params.get("X-Title")
    if isinstance(x_title, str) and x_title.strip():
        headers["X-Title"] = x_title.strip()
```

Fence rules (strict):
- Header tree → `#headers# ... #headers#`
- Classification JSON → `#classes# ... #classes#`
- Compliance JSON → `#compliance# ... #compliance#`

## Run-of-Show
- Parse → Headers → Specs → Risk → Approve → Export with golden tests for EPF/MFC.
- Never proceed to the next phase until Acceptance Checks pass.
- Prefer local-first; enable OpenRouter only when required.

---

Tip: Each phase agent includes an Audit block (confirm what exists) and a Patch block (apply changes). Always perform Audit before Patch.
