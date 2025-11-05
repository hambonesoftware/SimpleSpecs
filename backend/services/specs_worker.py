
"""
specs_worker: runs the Specs "buckets" in parallel against an LLM.
This module is intentionally self-contained so it can be dropped into the project
without touching the rest of the pipeline. It will:

- Load the parsed text for a document from the artifact_store if available (PARSED_TEXT).
  If not available, it will try to locate the uploaded PDF bytes and parse them here.
- Fire off multiple prompt calls concurrently (one per bucket) to the configured LLM.
- Return a dictionary with per-bucket results and light metadata.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session

# Attempt project-local imports; keep soft fallbacks so this stays drop-in.
from backend.models import Document, DocumentArtifactType  # type: ignore
from backend.services.artifact_store import (
    get_cached_artifact,
    store_artifact,
)  # type: ignore
from backend.utils.spec_trace import SpecTracer

logger = logging.getLogger(__name__)

# ---------- Configuration (env-driven so we don't edit config module) ----------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
SPECS_LLM_MODEL = os.getenv("SPECS_LLM_MODEL", os.getenv("HEADERS_LLM_MODEL", "anthropic/claude-3.5-sonnet"))
SPECS_LLM_TIMEOUT_S = float(os.getenv("SPECS_LLM_TIMEOUT_S", "120"))
SPECS_MAX_CONCURRENCY = int(os.getenv("SPECS_MAX_CONCURRENCY", "4"))

# Artifact constants
PARSED_TEXT_ARTIFACT_TYPE = getattr(DocumentArtifactType, "PARSED_TEXT", DocumentArtifactType.HEADER_TREE)
SPEC_BUCKET_ARTIFACT_TYPE = getattr(DocumentArtifactType, "SPEC_BUCKETS", DocumentArtifactType.JSON if hasattr(DocumentArtifactType, "JSON") else DocumentArtifactType.HEADER_TREE)
BUCKET_ARTIFACT_KEY = "spec_buckets"

# ------------- Bucket definitions (minimal examples; extend as needed) ---------
# Each bucket has a "name" and a "prompt" template. The document text is appended.
# You can add your own prompts or swap these for your existing ones.
BUCKETS: List[Dict[str, str]] = [
    {"name": "mechanical", "prompt": """You are a rigorous Mechanical Specifications Extractor.

GOAL
Extract ONLY mechanical-engineering requirements and best-practice specifications from the provided document SECTION. Focus on norms, constraints, limits, materials, finishes, tolerances, load/strength, fasteners, threads, torque, fits, GD&T, welding/brazing, machining, coatings, lubrication, pneumatics/hydraulics, guards/safety, ergonomics/maintenance/assembly, inspection/testing, documentation/marking/labels/packaging, environmental (temperature, dust, IP rating), vibration/noise, reliability/life, and referenced standards (ISO/ANSI/ASME/ASTM/etc.).

SCOPE
• Work strictly within the supplied SECTION text/metadata; do not infer outside facts.
• Ignore TOCs, running headers/footers, figure/table captions unless they state normative requirements.
• If the SECTION contains non-mechanical content, return an empty array.

INCLUSION RULES
Treat as mechanical when the clause is:
• Normative: uses SHALL/MUST/REQUIRED/IS TO/NEVER/NOT PERMITTED
• Strongly recommended best practice: SHOULD/RECOMMENDED
• Hard constraints: numeric limits, units, tolerances, grades, classes, surface finish, hardness, torque, thread specification, material callouts, protection ratings, safety guards, interlocks, clearances, environmental ranges
• Process/verification: inspection/test methods the mechanical engineer must follow

EXCLUSION RULES
• Purely administrative (dates, email, pricing), software-only, electrical-only unless they impose a mechanical constraint (e.g., clearance for conduit).
• Vague narrative with no actionable constraint.

OUTPUT RULES
• Return a single JSON object in one fenced JSON block marked MECHSPECS.
• Quote requirement text VERBATIM (no paraphrasing) in `text`. If a clause spans multiple lines, combine them; do not duplicate.
• Use the provided metadata (page numbers, header path, global line indexes) if available; otherwise set null.
• Classify each item precisely and add a brief rationale (one sentence).
• Be conservative: high confidence only when the clause is clearly mechanical and normative/actionable.

ENUMS
• requirement_level: ["MUST","SHOULD","MAY","INFO"]
• type: ["requirement","best_practice","constraint","test","documentation","safety","definition"]
• category (pick the most specific, add more if needed): ["materials","coatings","tolerances","gdandt","loads","fasteners","threads","torque","fits","welding","machining","surface_finish","lubrication","hydraulics","pneumatics","guards","ergonomics","maintenance","inspection","testing","marking","packaging","environmental","reliability","nvh","other"]

VALIDATION
• Do not invent numbers or standards.
• Units must appear in source text to record them.
• confidence in [0.0–1.0].
\n\n-- Document --\n"""},
    {"name": "electrical", "prompt": """You are a rigorous Electrical Specifications Extractor.

GOAL
Extract ONLY electrical-engineering requirements and best-practice specifications from the provided document SECTION. Focus on norms, constraints, limits, and procedures a practicing electrical engineer must follow: voltage/current/power, phase/frequency, grounding & bonding, insulation, conductor sizing & ampacity, wiring methods (cable, tray, conduit), color codes, device ratings, circuit protection (breakers/fuses), short-circuit & available fault current, arc-flash boundaries/labels, isolation & LOTO, safety circuits (E-Stops, safety relays), SIL/PL targets, interlocks, enclosures (IP/NEMA), EMC/EMI & shielding/filtering, harmonics/power quality, panel building, PLC/controls & I/O wiring, sensors/actuators supply levels, connectors/terminations & torque, routing/segregation (power vs signal), labeling/marking, schematics, testing (IR/megger, hipot, continuity, FAT/SAT), documentation, environmental (temperature, humidity), and referenced standards (NEC/NFPA 70, NFPA 79, IEC 60204-1, UL/CE/CSA/IEC).

SCOPE
• Work strictly within the supplied SECTION text/metadata; do not add outside knowledge.
• Ignore TOCs, running headers/footers, and purely illustrative figure/table captions unless they state normative requirements.
• If the SECTION has no electrical content, return an empty array.

INCLUSION RULES
Count as electrical when the clause is:
• Normative: SHALL/MUST/REQUIRED/IS TO/NOT PERMITTED
• Strong recommendation: SHOULD/RECOMMENDED
• Hard constraints: numeric limits, units, ratings, wire sizes, breaker sizes, clearances, temperature ranges, protection classes, enclosure ratings, torque values, color codes, EMC/EMI constraints
• Process/verification the electrical engineer must perform (tests, inspections, labeling)

EXCLUSION RULES
• Administrative (dates, submittals, pricing), mechanical-only, or software-only unless they impose an electrical constraint (e.g., supply voltage for a sensor).
• Vague narrative with no actionable constraint.

OUTPUT RULES
• Return ONE JSON object in a single fenced JSON block marked ELECSPECS.
• Quote requirement text VERBATIM in `text` (no paraphrasing). If a clause spans lines, combine them into one item.
• Use provided metadata fields if available; otherwise set null.
• Classify precisely and add a one-sentence rationale.
• Be conservative: high confidence only when clearly electrical AND normative/actionable.

ENUMS
• requirement_level: ["MUST","SHOULD","MAY","INFO"]
• type: ["requirement","best_practice","constraint","test","documentation","safety","definition"]
• category (pick most specific; add more if needed): [
  "power_distribution","voltage_levels","current_power","frequency_phase",
  "grounding_bonding","insulation","conductor_sizing","wiring_methods",
  "cable_tray_conduit","color_codes","device_ratings","circuit_protection",
  "short_circuit_fault_current","arc_flash","isolation_loto","safety_circuits",
  "sil_pl","interlocks","enclosures","emc_emi","shielding_filtering",
  "harmonics_power_quality","plc_controls","io_wiring","control_panels",
  "sensors_actuators","connectors_terminations","torque",
  "routing_segregation","labeling_marking","schematics",
  "testing_inspection","documentation","environmental","other"
]

VALIDATION
• Do not invent numbers or standards.
• Units/ratings must appear in the source text to be recorded.
• confidence must be in [0.0–1.0].
\n\n-- Document --\n"""},
    {"name": "controls", "prompt": """You are a rigorous Controls Specifications Extractor.

GOAL
Extract ONLY controls-engineering requirements and best-practice specifications from the provided document SECTION. Focus on constraints and procedures a controls engineer must follow: PLC/IPC standards (IEC 61131-3), program structure, naming conventions, modes & states (Auto/Manual/Maintenance), permissives & interlocks, alarms & events (ISA-18.2), HMI/SCADA (ISA-101 style/graphics), safety PLC & safety functions (ISO 13849, IEC 62061/61508), emergency stops, safety zones, risk reduction measures, I/O allocation & signal types, scaling/filters/debounce, sequencing/recipes/batch (ISA-88), motion/drives/VFD parameters & STO, robot/cell interfaces & handshakes, network/fieldbus (EtherNet/IP, PROFINET, Modbus, CANopen), addressing & determinism, time sync (PTP), performance/scan-cycle/latency/throughput, diagnostics/fault handling/retry/backoff/timeouts, data logging/historian/time stamping, traceability, user roles/authentication/authorization, audit logging, cybersecurity hardening (IEC 62443, NIST 800-82), FAT/SAT/IO checkout/validation/acceptance criteria, and required documentation (I/O list, C&E matrix, sequences, program printouts, alarm list).

SCOPE
• Work strictly within the supplied SECTION text/metadata; do not add outside facts.
• Ignore TOCs, running headers/footers, and purely illustrative captions unless they state normative requirements.
• If the SECTION has no controls content, return an empty array.

INCLUSION RULES
Count as controls when the clause is:
• Normative: SHALL/MUST/REQUIRED/NOT PERMITTED
• Strong recommendation: SHOULD/RECOMMENDED
• Hard constraints: sequence rules, interlock conditions, alarm setpoints/priority/annunciation rules, program structure and naming, I/O type/scan class, PLC cycle time limits, motion/drives parameters, interface handshakes, safety logic behavior, cybersecurity settings, test/validation procedures.
• Verification steps the controls engineer must perform (e.g., IO checkout, FAT/SAT, alarm testing).

EXCLUSION RULES
• Purely mechanical/electrical without a controls implication (e.g., wire gauge) unless it constrains logic, addressing, signals, or PLC hardware behavior.
• Administrative text (pricing, dates, submittal routing) and vague narrative with no actionable constraint.

OUTPUT RULES
• Return ONE JSON object in a single fenced JSON block marked CTRLSPECS.
• Quote requirement text VERBATIM in `text` (no paraphrasing). If a clause spans lines, combine into one item; do not duplicate.
• Use provided metadata if available; otherwise set null.
• Classify precisely and add a one-sentence rationale.
• Be conservative: high confidence only when clearly controls-related AND normative/actionable.

ENUMS
• requirement_level: ["MUST","SHOULD","MAY","INFO"]
• type: ["requirement","best_practice","constraint","test","documentation","safety","definition"]
• category (pick the most specific; add more if needed):
  ["plc_programming","safety_plc","modes_states","sequence_of_operations","permissives_interlocks",
   "alarm_management","hmi_scada","io_allocation","signals_scaling","diagnostics_faults",
   "motion_drives","robot_interface","batch_recipes","data_logging_historian","reporting_traceability",
   "networking","fieldbus","time_sync","performance_timing","versioning_configuration",
   "cybersecurity","user_management","audit_logging","testing_validation","fat_sat",
   "documentation","naming_standards","standards_compliance","safety_zones","risk_assessment","other"]

VALIDATION
• Do not invent numbers, parameters, or standards.
• Units/limits must appear in the source text to record them.
• confidence must be in [0.0–1.0].
\n\n-- Document --\n"""},
    {"name": "software", "prompt": """You are a rigorous Software Specifications Extractor.

GOAL
Extract ONLY software-engineering requirements and best-practice specifications from the provided document SECTION. Focus on constraints and procedures a software engineer must follow: architecture/design (layers, modules, patterns), interfaces/APIs, protocols, data models & formats, configuration, state machines, error handling & retries/backoff, logging, observability (metrics, monitoring, alerting, tracing), security (authN/Z, roles, encryption, key/secrets management, input validation, OWASP/ASVS), privacy, audit logging, performance/latency/throughput/memory limits, scalability, availability/reliability (SLA/SLO), concurrency/real-time/timing, transactions/idempotency, databases/schemas/migrations, caching, messaging/queues/streaming, versioning/compatibility, deployment/runtime (containers, services), CI/CD, testing (unit/integration/system/e2e, coverage thresholds), static analysis/linting, code review, documentation/traceability, change control, SBOM/licensing/compliance, backups/DR (RTO/RPO), safety-related software compliance (e.g., IEC 61508) if present, and referenced standards (ISO/IEC, NIST, OWASP, etc.) that appear in the text.

SCOPE
• Work strictly within the supplied SECTION text/metadata; do not add outside facts.
• Ignore TOCs, running headers/footers, and purely illustrative captions unless they state normative requirements.
• If the SECTION has no software content, return an empty array.

INCLUSION RULES
Count as software when the clause is:
• Normative (SHALL/MUST/REQUIRED/NOT PERMITTED/IS TO)
• Strong recommendation (SHOULD/RECOMMENDED)
• Hard constraints: numeric limits, units, SLAs/SLOs, thresholds, coverage %, encryption modes, protocol versions, API stability/compatibility rules, roles/permissions, timing windows, retry limits, memory/CPU caps, etc.
• Verification steps the software engineer must perform (tests, evidence, documentation, sign-offs).

EXCLUSION RULES
• Purely mechanical/electrical/controls unless it imposes a software obligation (e.g., “software shall log E-stop events with timestamp and operator ID”).
• Administrative text (pricing, contact lists) or vague narrative with no actionable constraint.

OUTPUT RULES
• Return ONE JSON object in a single fenced JSON block marked SWESPECS.
• Quote requirement text VERBATIM in `text` (no paraphrasing). Merge multi-line clauses into one item; do not duplicate.
• Use provided metadata fields if available; otherwise set null.
• Classify precisely and add a one-sentence rationale.
• Be conservative: high confidence only when clearly software-related AND normative/actionable.

ENUMS
• requirement_level: ["MUST","SHOULD","MAY","INFO"]
• type: ["requirement","best_practice","constraint","test","documentation","safety","definition"]
• category (pick the most specific; add more if needed):
  ["architecture_design","interfaces_api","protocols","data_models","data_formats",
   "configuration_management","state_machines","error_handling","logging",
   "observability","performance","reliability_availability","scalability",
   "concurrency_real_time","transactions_idempotency","database_storage",
   "caching","messaging_eventing","versioning_release","compatibility",
   "deployment_runtime","containers_orchestration","ci_cd",
   "testing_unit","testing_integration","testing_system","testing_e2e","test_coverage",
   "static_analysis","code_style_reviews","documentation","traceability","change_control",
   "security_auth","security_encryption","security_input_validation","secrets_management",
   "privacy","audit_logging","sbom_licensing","backups_dr","safety_compliance","other"]

VALIDATION
• Do not invent numbers, parameters, or standards.
• Units/limits/standards must appear in the source text to record them.
• confidence ∈ [0.0, 1.0].
\n\n-- Document --\n"""},
]

# ---------- Utilities ----------------------------------------------------------
async def _openrouter_chat(
    prompt: str,
    *,
    tracer: SpecTracer | None = None,
    bucket: str | None = None,
) -> str:
    """
    Minimal OpenRouter client using the unofficial fetch via httpx for a single-turn chat.
    We keep it inline to avoid adding dependencies elsewhere in the repo.
    """
    import httpx  # SimpleSpecs already depends on httpx via other paths

    logger.debug(
        "[specs_worker] _openrouter_chat invoked",
        {"prompt_preview": prompt[:200], "prompt_length": len(prompt)},
    )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/hambonesoftware/SimpleSpecs",
        "X-Title": "SimpleSpecs",
        "Content-Type": "application/json",
    }

    body = {
        "model": SPECS_LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a precise specifications extraction assistant. Reply with JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
    }

    timeout = httpx.Timeout(SPECS_LLM_TIMEOUT_S)
    if tracer:
        tracer.llm_request(bucket=bucket, request_headers=headers, request_body=body)

    async with httpx.AsyncClient(timeout=timeout) as client:
        logger.debug(
            "[specs_worker] _openrouter_chat sending request",
            {"model": SPECS_LLM_MODEL, "temperature": body["temperature"]},
        )
        r = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body)
        logger.debug(
            "[specs_worker] _openrouter_chat received response",
            {"status_code": r.status_code, "headers": dict(r.headers)},
        )
        try:
            payload = r.json()
        except ValueError:
            payload = {"raw": r.text}

        if tracer:
            tracer.llm_response(
                bucket=bucket,
                status_code=r.status_code,
                response_headers=dict(r.headers),
                response_body=payload,
            )

        r.raise_for_status()
        try:
            content = payload["choices"][0]["message"]["content"]  # type: ignore[index]
            logger.debug(
                "[specs_worker] _openrouter_chat parsed content",
                {"content_preview": content[:200], "content_length": len(content)},
            )
            return content
        except Exception:
            logger.exception("[specs_worker] _openrouter_chat unexpected response structure", exc_info=True)
            return json.dumps({"error": "Unexpected response", "raw": payload})


def _best_doc_text_from_cache(
    session: Session,
    document: Document,
    *,
    settings: Any | None = None,
    tracer: SpecTracer | None = None,
) -> Tuple[str, Optional[str]]:
    """
    Try to obtain the best available "full text" for the document from the artifact store.
    Returns (text, doc_hash?|None).
    """
    logger.debug(
        "[specs_worker] _best_doc_text_from_cache invoked",
        {"document_id": document.id},
    )
    if tracer:
        tracer.function_call("_best_doc_text_from_cache", document_id=document.id)
    # Prefer a dedicated PARSED_TEXT artifact if your repo writes one.
    for key in ("parsed_text", "fulltext", "plain_text"):
        logger.debug(
            "[specs_worker] _best_doc_text_from_cache attempting cache lookup",
            {"document_id": document.id, "key": key},
        )
        if tracer:
            tracer.decision("doc_text_cache_lookup", key=key)
        cached = get_cached_artifact(
            session=session,
            document_id=document.id,
            artifact_type=PARSED_TEXT_ARTIFACT_TYPE,
            key=key,
            inputs=None,
        )
        if cached and isinstance(cached.body, dict):
            text = cached.body.get("text") or cached.body.get("content") or ""
            if text:
                doc_hash = cached.body.get("doc_hash")
                logger.debug(
                    "[specs_worker] _best_doc_text_from_cache cache hit",
                    {
                        "document_id": document.id,
                        "key": key,
                        "text_length": len(text),
                        "doc_hash": doc_hash,
                    },
                )
                if tracer:
                    tracer.decision(
                        "doc_text_cache_hit",
                        key=key,
                        text_length=len(text),
                        doc_hash=doc_hash,
                    )
                return text, doc_hash
        if tracer:
            tracer.decision("doc_text_cache_miss", key=key)

    # Fall back to reading the PDF and extracting on the fly (basic PyMuPDF approach).
    # We avoid adding new heavy deps; SimpleSpecs likely already uses PyMuPDF elsewhere.
    try:
        from pathlib import Path

        logger.debug(
            "[specs_worker] _best_doc_text_from_cache falling back to PyMuPDF",
            {
                "document_id": document.id,
                "filename": document.filename,
                "settings_upload_dir": getattr(settings, "upload_dir", None),
            },
        )
        if tracer:
            tracer.decision(
                "doc_text_fallback_pymupdf",
                filename=document.filename,
                upload_dir=getattr(settings, "upload_dir", None),
            )
        import fitz  # PyMuPDF

        candidate_dirs: List[Path] = []
        if settings and getattr(settings, "upload_dir", None):
            candidate_dirs.append(Path(settings.upload_dir))
        try:
            from backend.paths import UPLOAD_DIR  # type: ignore

            candidate_dirs.append(Path(UPLOAD_DIR))  # type: ignore[arg-type]
        except Exception:
            logger.debug(
                "[specs_worker] _best_doc_text_from_cache default upload dir unavailable",
                {"document_id": document.id},
            )

        checked_paths: List[str] = []
        for base_dir in candidate_dirs:
            if not document.filename:
                continue
            for relative in (
                Path(str(document.id or "")) / document.filename,
                Path(document.filename),
            ):
                pdf_path = (base_dir / relative).resolve()
                checked_paths.append(str(pdf_path))
                if not pdf_path.exists():
                    continue
                text_parts: List[str] = []
                with fitz.open(pdf_path) as doc_obj:
                    for page in doc_obj:
                        text_parts.append(page.get_text("text"))
                joined = "\n".join(text_parts)
                logger.debug(
                    "[specs_worker] _best_doc_text_from_cache extracted via PyMuPDF",
                    {
                        "document_id": document.id,
                        "text_length": len(joined),
                        "pdf_path": str(pdf_path),
                    },
                )
                if tracer:
                    tracer.decision(
                        "doc_text_pymupdf_success",
                        pdf_path=str(pdf_path),
                        text_length=len(joined),
                    )
                return joined, None

        logger.error(
            "[specs_worker] _best_doc_text_from_cache no PDF path found",
            {
                "document_id": document.id,
                "filename": document.filename,
                "checked_paths": checked_paths,
            },
        )
        if tracer:
            tracer.decision(
                "doc_text_pdf_not_found",
                filename=document.filename,
                checked_paths=checked_paths,
            )
        logger.debug(
            "[specs_worker] _best_doc_text_from_cache falling back to PyMuPDF",
            {"document_id": document.id, "filename": document.filename},
        )
        import fitz  # PyMuPDF
        # Document is typically saved in uploads/ by filename; try that.
        from backend.paths import UPLOAD_DIR  # type: ignore
        import os
        pdf_path = os.path.join(UPLOAD_DIR, document.filename)  # type: ignore[attr-defined]
        text_parts: List[str] = []
        with fitz.open(pdf_path) as doc:
            for page in doc:
                text_parts.append(page.get_text("text"))
        joined = "\n".join(text_parts)
        logger.debug(
            "[specs_worker] _best_doc_text_from_cache extracted via PyMuPDF",
            {"document_id": document.id, "text_length": len(joined)},
        )
        if tracer:
            tracer.decision(
                "doc_text_pymupdf_success",
                pdf_path=str(pdf_path),
                text_length=len(joined),
            )
        return joined, None
    except Exception as exc:
        logger.exception(
            "[specs_worker] _best_doc_text_from_cache fallback failed",
            {
                "document_id": document.id,
                "filename": getattr(document, "filename", None),
            },
            exc_info=True,
        )
        if tracer:
            tracer.decision(
                "doc_text_fallback_error",
                error=str(exc),
                filename=getattr(document, "filename", None),
            )
        return "", None
   

async def _run_single_bucket(
    bucket: Dict[str, str],
    doc_text: str,
    *,
    tracer: SpecTracer | None = None,
) -> Dict[str, Any]:
    name = bucket["name"]
    prompt = bucket["prompt"] + doc_text
    try:
        logger.debug(
            "[specs_worker] _run_single_bucket starting",
            {"bucket": name, "prompt_length": len(prompt)},
        )
        if tracer:
            tracer.function_call("_run_single_bucket", bucket=name, prompt_length=len(prompt))
        raw = await _openrouter_chat(prompt, tracer=tracer, bucket=name)
        # Try to coerce to JSON when possible
        try:
            data = json.loads(raw)
        except Exception:
            data = {"raw": raw}
        logger.debug(
            "[specs_worker] _run_single_bucket success",
            {
                "bucket": name,
                "response_preview": raw[:200],
                "parsed_keys": list(data.keys()) if isinstance(data, dict) else None,
            },
        )
        if tracer:
            tracer.decision(
                "bucket_parse",
                bucket=name,
                parsed_keys=list(data.keys()) if isinstance(data, dict) else None,
            )
            tracer.outcome(
                "bucket",
                bucket=name,
                ok=True,
                response_preview=raw[:200],
            )
        return {"name": name, "ok": True, "data": data}
    except Exception as exc:
        logger.exception(
            "[specs_worker] _run_single_bucket failed (bucket=%s)",
            name,
            exc_info=True,
        )
        if tracer:
            tracer.outcome("bucket", bucket=name, ok=False, error=str(exc))
        return {"name": name, "ok": False, "error": str(exc)}


async def run_all_buckets_concurrently(
    *,
    session: Session,
    document: Document,
    settings: Any = None,
    tracer: SpecTracer | None = None,
) -> Dict[str, Any]:
    """
    Orchestrates a single concurrent run of all BUCKETS for one document.
    Returns a dictionary with "buckets" (mapping) and light run metadata.
    """
    logger.debug(
        "[specs_worker] run_all_buckets_concurrently invoked",
        {
            "document_id": document.id,
            "bucket_names": [bucket["name"] for bucket in BUCKETS],
        },
    )
    bucket_names = [bucket["name"] for bucket in BUCKETS]
    if tracer:
        tracer.function_call(
            "run_all_buckets_concurrently",
            document_id=document.id,
            bucket_names=bucket_names,
        )
        tracer.metadata(
            document_id=document.id,
            document_filename=getattr(document, "filename", None),
            bucket_names=bucket_names,
        )
    doc_text, doc_hash = _best_doc_text_from_cache(
        session, document, settings=settings, tracer=tracer
    )
    logger.debug(
        "[specs_worker] run_all_buckets_concurrently document text status",
        {
            "document_id": document.id,
            "doc_hash": doc_hash,
            "text_available": bool(doc_text),
            "text_length": len(doc_text or ""),
        },
    )
    if tracer:
        tracer.decision(
            "doc_text_status",
            document_id=document.id,
            doc_hash=doc_hash,
            text_available=bool(doc_text),
            text_length=len(doc_text or ""),
        )
    if not doc_text:
        # We don't fail hard; return an informative structure
        logger.debug(
            "[specs_worker] run_all_buckets_concurrently no doc text",
            {"document_id": document.id},
        )
        if tracer:
            tracer.outcome(
                "run",
                document_id=document.id,
                ok=False,
                reason="no_parsed_text",
            )
        return {
            "doc_id": document.id,
            "doc_hash": doc_hash,
            "buckets": {},
            "messages": ["No parsed text available for document; unable to run buckets."],
        }

    sem = asyncio.Semaphore(SPECS_MAX_CONCURRENCY)
    logger.debug(
        "[specs_worker] run_all_buckets_concurrently semaphore created",
        {"max_concurrency": SPECS_MAX_CONCURRENCY},
    )

    async def guarded(bucket):
        async with sem:
            logger.debug("[specs_worker] run_all_buckets_concurrently entering bucket", {"bucket": bucket["name"]})
            return await _run_single_bucket(bucket, doc_text, tracer=tracer)

    results = await asyncio.gather(*(guarded(b) for b in BUCKETS))
    logger.debug(
        "[specs_worker] run_all_buckets_concurrently gathered results",
        {
            "document_id": document.id,
            "result_count": len(results),
            "ok_buckets": [r["name"] for r in results if r.get("ok")],
            "error_buckets": [r["name"] for r in results if not r.get("ok")],
        },
    )

    buckets_out: Dict[str, Any] = {}
    messages: List[str] = []
    for item in results:
        name = item["name"]
        if item.get("ok"):
            buckets_out[name] = item.get("data")
        else:
            buckets_out[name] = {"error": item.get("error", "unknown")}
            messages.append(f"Bucket {name} failed: {item.get('error')}")
        if tracer:
            tracer.outcome(
                "bucket_result",
                bucket=name,
                ok=bool(item.get("ok")),
                error=item.get("error"),
            )

    logger.debug(
        "[specs_worker] run_all_buckets_concurrently assembled output",
        {
            "document_id": document.id,
            "bucket_keys": list(buckets_out.keys()),
            "messages": messages,
        },
    )
    if tracer:
        tracer.outcome(
            "run",
            document_id=document.id,
            ok=True,
            message_count=len(messages),
        )
    return {
        "doc_id": document.id,
        "doc_hash": doc_hash,
        "buckets": buckets_out,
        "messages": messages,
    }
