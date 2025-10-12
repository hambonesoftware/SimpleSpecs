# Phase 4 — Header Detector & Tree Builder

## Objective
Detect headers/subheaders and build hierarchical structure.

## Key Tasks
1. Implement `backend/services/headers_detect.py`.
2. Add regex library for numbering patterns (Arabic, Roman, Alpha).
3. Rank candidates by font, size, boldness, indent, and page position.
4. Filter TOCs, footers, duplicates; infer missing levels.

## Deliverables
- Full header tree JSON
- Confidence scoring metadata

## Exit Criteria
- Accurate hierarchical tree on both PDFs.
