# Standards Hardening (ASME / ISO / IEC)

This plan uses standards-informed lexical priors and gates to **boost recall** and **reduce hallucinations**.

## Canonical Families
- **ASME Y14.x** — engineering drawing and documentation practices (titles, notes, revisions).
- **ISO 9001** — quality management; ensures traceability and controlled documents.
- **ISO 12100** — safety of machinery; terminology and risk assessment.
- **IEC 60204-1** — safety of machinery — electrical equipment of machines.

## Hardening Tactics
- **Lexical gates**: boost segments with terms like *Scope, Purpose, Definitions, Applicable Documents, Bill of Materials, Interface, Tolerances, Revision Control, Safety Requirements, Protective Measures, Electrical Equipment, Functional Safety*.
- **TOC and running-header suppression**: prevent false positives in header detection.
- **Fallback extraction**: OCR or MinerU when native text blocks are missing.
- **Risk gates**: if mandatory sections by standard family are absent, raise risk score and mark as “At Risk”.

## Term Lists (example skeletons)
- `asme_y14_terms.json`
- `iso_9001_terms.json`
- `iso_12100_terms.json`
- `iec_60204_terms.json`

> Maintain these in `backend/resources/terms/` and version under tests with golden snapshots.
