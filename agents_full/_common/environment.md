# Environment Defaults

Repo: hambonesoftware/SimpleSpecs
Python: 3.11–3.12

## Common Variables
```
ALLOW_ORIGINS=http://localhost:3000
PARSER_MULTI_COLUMN=true
HEADERS_SUPPRESS_TOC=true
HEADERS_SUPPRESS_RUNNING=true
PARSER_ENABLE_OCR=false

RAG_ENABLE=true
RAG_CHUNK_MODE=section
RAG_LIGHT_MODE=1
RAG_MODEL_PATH=./models/all-MiniLM-L6-v2
RAG_INDEX_DIR=./.rag_index

# MinerU LLM fallback (Phase-1+; disabled by default)
LLM_FALLBACK_ENABLE=false
LLM_FALLBACK_PROVIDER=openrouter
OPENROUTER_API_KEY=changeme
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM_FALLBACK_MODEL=anthropic/claude-3.5-sonnet
LLM_FALLBACK_MAX_TOKENS=2000
LLM_FALLBACK_TEMPERATURE=0.2
LLM_FALLBACK_PAGE_LIMIT=8
```
