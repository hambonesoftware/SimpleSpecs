# Phase 05 — LLM Integration Layer (OpenRouter / Ollama) (Agent Prompt)

## ROLE
You are a senior engineer executing this phase for the SimpleSpecs app. Audit first, Patch second. Keep existing public APIs stable.

## INPUTS
- Repository: the SimpleSpecs repo connected in this session.
- Plan reference: the matching phase in `plan.zip`.
- Sample PDFs: `samples/EPF.pdf`, `samples/MFC.pdf` (or as present in repo).

## OBJECTIVES
- Abstract provider with token bump, headers passthrough, retries, and cache.

## CONSTRAINTS
- Python 3.12 + FastAPI backend; HTML/CSS + ESM-JS frontend.
- Use OpenRouter as primary LLM provider with the provided hardening.
- Maintain strict fenced outputs for LLM responses.
- Respect `.env` feature flags.

## AUDIT (do this before changing anything)
- Inspect `services/llm.py` for `get_provider`, `call_openrouter`, `call_ollama`.
- Check for `max_tokens` bump and `HTTP-Referer`/`X-Title` passthrough.

## PATCH (apply changes if audit gaps exist)
- Implement hardened request builder with fences validation and retry on failure.
- Add exponential backoff and simple on-disk cache keyed by (prompt+hash+model).
- Expose metrics: tokens, latency, retries.

## TESTS
- Mock provider to simulate rate limits and invalid fence outputs; ensure retries succeed.
- Verify cache hits and cost logs.

## ACCEPTANCE CHECKS
- 100% provider unit tests; stable behavior across retries.

## DONE WHEN
- Downstream phases receive valid fenced payloads consistently.
