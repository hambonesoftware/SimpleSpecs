# SimpleSpecs — Agent Execution & Verification Guide (MinerU LLM Fallback Included)

This guide explains how to run every development phase of *SimpleSpecs* using the **agents_full** pack,
including the **MinerU-style OpenRouter fallback** for parsing when native methods fail.

---

## 🧭 Phases

| Phase | Branch | Purpose |
|------|--------|---------|
| **P0** | `p0-bootstrap` | Tooling, CI, CORS, smoke test, governance |
| **P1** | `p1-headers` | PDF parsing + header extraction, **MinerU LLM fallback (OpenRouter)** |
| **P2** | `p2-specs-rag` | One-chunk-per-section atomization, hybrid RAG search (offline-first) |

*(Future phases can be added following the same pattern.)*

---

## ⚙️ Environment (quick start)

See `agents_full/_common/environment.md` for full details. Key vars:

```bash
# Parsing
export PARSER_MULTI_COLUMN=true
export HEADERS_SUPPRESS_TOC=true
export HEADERS_SUPPRESS_RUNNING=true
export PARSER_ENABLE_OCR=false

# RAG / Chunking (P2)
export RAG_ENABLE=true
export RAG_CHUNK_MODE=section     # Enforce one-chunk-per-section
export RAG_LIGHT_MODE=1           # Deterministic stub embeddings in CI
export RAG_MODEL_PATH=./models/all-MiniLM-L6-v2
export RAG_INDEX_DIR=./.rag_index

# MinerU-style LLM fallback (P1+; disabled by default)
export LLM_FALLBACK_ENABLE=false  # set true to enable
export LLM_FALLBACK_PROVIDER=openrouter
export OPENROUTER_API_KEY=your_key_here
export OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
export LLM_FALLBACK_MODEL=anthropic/claude-3.5-sonnet
export LLM_FALLBACK_MAX_TOKENS=2000
export LLM_FALLBACK_TEMPERATURE=0.2
export LLM_FALLBACK_PAGE_LIMIT=8
```

**Offline-first default:** keep `LLM_FALLBACK_ENABLE=false` and `RAG_LIGHT_MODE=1` for CI and developer machines.

---

## 🪄 How to Use with Codex

1) **Execute a phase**  
   Copy `agents_full/phases/pX/execute.md` → paste into Codex (GitHub connector on repo).  
   Codex creates the branch, commits work in slices, and opens a PR.

2) **Verify the phase**  
   Copy `agents_full/phases/pX/verify.md` → paste into the same Codex chat.  
   Codex returns a PASS/FAIL report per `_common/verify_report_template.md`.

3) **Fix & Merge**  
   Apply suggested fixes (files + tests). Re-run verify until all PASS. Merge PR. Next phase.

---

## 🔧 MinerU / LLM Fallback (P1)

When native parsing + OCR do not yield a usable header tree, a **flag-gated** fallback can call **OpenRouter**
to reconstruct headers (MinerU-style prompt), returning strict JSON. Verification requires:

- `backend/services/mineru_fallback.py` exists and uses the same OpenRouter pattern you already use.
- Fallback is only active when `LLM_FALLBACK_ENABLE=true` and `OPENROUTER_API_KEY` is set.
- Unit tests **mock** the OpenRouter call; no network in tests unless `ONLINE_TESTS=1`.
- Phase-1 verify checks these conditions explicitly.

---

## ✅ Phase Exit Criteria (all phases)

- ✅ Acceptance bullets in the phase’s `execute.md` are met  
- ✅ Existing APIs unbroken; new endpoints additive and behind flags  
- ✅ CI green (pre-commit, lint/type/tests, coverage visible)  
- ✅ Docs updated (`README`, `docs/DEV_SETUP.md`, `.env.example`)  
- ✅ Offline-first and deterministic tests  
- ✅ MinerU fallback: gated, tested, documented (P1+)

---

## 🧩 Pack Layout

```
agents_full/
├── manifest.yaml
├── _common/
│   ├── standard_agent.md
│   ├── guardrails.md
│   ├── environment.md
│   └── verify_report_template.md
└── phases/
    ├── p0/
    │   ├── execute.md
    │   └── verify.md
    ├── p1/
    │   ├── execute.md  # includes MinerU fallback deliverables
    │   └── verify.md   # checks fallback wiring & tests
    └── p2/
        ├── execute.md
        └── verify.md
```

**Workflow mantra:** *Execute → Verify → Fix → Merge → Next Phase*.
