# Config & Feature Toggles

Environment variables (see `.env.template`):
```
OPENROUTER_API_KEY=
LLM_PROVIDER=openrouter        # 'openrouter' or 'ollama'
PARSER_MULTI_COLUMN=true
PARSER_ENABLE_OCR=true
HEADERS_SUPPRESS_TOC=true
HEADERS_SUPPRESS_RUNNING=true
MINERU_FALLBACK=true
DB_URL=sqlite:///./simplespecs.db
```

LLM request hardening (pseudo):
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
