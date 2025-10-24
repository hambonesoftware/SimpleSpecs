# Guardrails (Apply Across All Phases)

## API Stability
- Never break existing routes or response schemas.
- New endpoints must be additive and behind feature flags.

## Phase Boundaries
- Only implement what the current phase declares.
- One PR per phase from a fresh branch.

## Determinism & Offline-First
- Tests deterministic across OSes; seed randomness.
- CI uses `RAG_LIGHT_MODE=1` and **never** hits external networks by default.
- Tests that require the network must be marked `@pytest.mark.online` and skipped unless `ONLINE_TESTS=1`.

## Section-Chunking Rule (Phase 2+)
- With `RAG_CHUNK_MODE=section`, ignore token/overlap configs.
- Enforce 1:1 section ↔ chunk.

## MinerU LLM Fallback Safety (Phase 1+)
- Fallback triggered **only** when native+OCR fail **and** `LLM_FALLBACK_ENABLE=true` with API key set.
- Use the existing OpenRouter calling convention.
- Tests mock network; no secrets in repo.

## CORS & Secrets
- CORS origin must come from `ALLOW_ORIGINS`.
- No '*' in production configs. No secrets in code or committed files.

## PR Evidence
- Every PR includes lint/type/test logs and a short file diff summary.
