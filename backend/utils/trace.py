from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .logging import configure_logging


LOGGER = configure_logging().getChild("headers.trace")


@dataclass(slots=True)
class TraceEvent:
    t: float
    type: str
    data: Dict[str, Any]


class HeaderTracer:
    """Collect structured events for header tracing (LLM + alignment + chunking)."""

    def __init__(
        self, run_id: Optional[str] = None, out_dir: str = "backend/logs/headers"
    ) -> None:
        self.run_id = run_id or str(uuid.uuid4())
        self.out_dir = out_dir
        self.events: List[TraceEvent] = []
        os.makedirs(self.out_dir, exist_ok=True)
        self._path = os.path.join(self.out_dir, f"{self.run_id}.jsonl")
        self._summary_path = os.path.join(self.out_dir, f"{self.run_id}.summary.json")

    # --- Emission API ---------------------------------------------------------
    def ev(self, event_type: str, **data: Any) -> None:
        """Record a generic event."""
        self.events.append(TraceEvent(t=time.time(), type=event_type, data=data))

    # Alias to support Protocol-style tracers (used by section_chunking.py)
    def emit(self, event_type: str, **data: Any) -> None:  # Protocol compat
        self.ev(event_type, **data)

    def log_call(self, name: str, **context: Any) -> None:
        """Record an invocation of *name* preserving call order."""
        self.ev("function_call", name=name, **context)
    # -------------------------------------------------------------------------

    def flush_jsonl(self) -> str:
        with open(self._path, "w", encoding="utf-8") as handle:
            for event in self.events:
                payload = {"t": event.t, "type": event.type, **event.data}
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        summary_payload = self._build_summary()
        with open(self._summary_path, "w", encoding="utf-8") as handle:
            json.dump(summary_payload, handle, ensure_ascii=False, indent=2)
        LOGGER.info("[headers] Search log saved: %s", self._path)
        LOGGER.info("[headers] Search summary saved: %s", self._summary_path)
        return self._path

    @property
    def path(self) -> str:
        return self._path

    @property
    def summary_path(self) -> str:
        return self._summary_path

    def as_list(self) -> List[Dict[str, Any]]:
        return [{"t": event.t, "type": event.type, **event.data} for event in self.events]

    def _build_summary(self) -> Dict[str, Any]:
        events = self.as_list()
        metadata: Dict[str, Any] = {}
        llm_headers: List[Dict[str, Any]] = []
        llm_requests: List[Dict[str, Any]] = []
        llm_raw_responses: List[str] = []
        llm_fenced_blocks: List[str] = []
        final_outline: Dict[str, Any] = {}
        decisions: List[Dict[str, Any]] = []
        elapsed: float | None = None
        function_calls: List[Dict[str, Any]] = []

        # --- Chunking aggregation buckets ------------------------------------
        # We expose a compact chunking summary for the Header Search report.
        chunking_passes = 0
        chunking_completes = 0
        chunk_bounds_resolved = 0
        chunk_skipped_inverted = 0
        header_missing_global = 0
        header_not_in_lines = 0
        line_index_indexed_total = 0
        line_index_missing_total = 0
        last_line_index_map: Dict[str, Any] = {}
        built_chunks: List[Dict[str, Any]] = []
        # ----------------------------------------------------------------------

        # Events that the UI should consider "decisions" (show in the list)
        decision_types = {
            # existing
            "candidate_found",
            "anchor_resolved",
            "fallback_triggered",
            "monotonic_violation",
            # new chunking-related visibility
            "chunking_start",
            "line_index_map_built",
            "header_missing_global",
            "header_not_in_lines",
            "chunk_bounds_resolved",
            "chunk_skipped_inverted",
            "chunk_built",
            "chunking_complete",
            # cache/info that influences behavior
            "cache_purged",
            "cache_bypassed",
        }

        for event in events:
            event_type = event.get("type")

            # --- Run metadata / timings
            if event_type == "start_run":
                metadata = {
                    key: value
                    for key, value in event.items()
                    if key not in {"t", "type"}
                }

            elif event_type == "final_outline":
                final_outline = {
                    "headers": list(event.get("headers", [])),
                    "sections": list(event.get("sections", [])),
                    "mode": event.get("mode"),
                    "messages": list(event.get("messages", [])),
                }
                if "elapsed_s" in event and elapsed is None:
                    elapsed = event.get("elapsed_s")

            elif event_type == "end_run":
                if elapsed is None:
                    elapsed = event.get("elapsed_s")
                final_outline.setdefault("mode", event.get("mode"))

            # --- LLM plumbing
            elif event_type == "llm_outline_received":
                llm_headers = list(event.get("headers", []))

            elif event_type == "llm_request":
                llm_requests.append(
                    {
                        "part": event.get("part"),
                        "total_parts": event.get("total_parts"),
                        "model": event.get("model"),
                        "temperature": event.get("temperature"),
                        "timeout_read": event.get("timeout_read"),
                        "params": event.get("params"),
                        "messages": event.get("messages", []),
                    }
                )

            elif event_type == "llm_raw_response":
                raw_parts = event.get("parts")
                if isinstance(raw_parts, list):
                    llm_raw_responses.extend(
                        str(part) for part in raw_parts if isinstance(part, str)
                    )
                elif isinstance(raw_parts, str):
                    llm_raw_responses.append(raw_parts)

                fenced_parts = event.get("fenced")
                if isinstance(fenced_parts, list):
                    llm_fenced_blocks.extend(
                        str(entry) for entry in fenced_parts if isinstance(entry, str)
                    )
                elif isinstance(fenced_parts, str):
                    llm_fenced_blocks.append(fenced_parts)

            # --- Call stack
            elif event_type == "function_call":
                call_entry: Dict[str, Any] = {
                    "order": len(function_calls) + 1,
                    "name": str(event.get("name", "")),
                }
                context = {
                    key: value
                    for key, value in event.items()
                    if key not in {"t", "type", "name"}
                }
                if context:
                    call_entry["context"] = context
                function_calls.append(call_entry)

            # --- Chunking visibility (aggregate while we loop)
            if event_type == "chunking_start":
                chunking_passes += 1

            elif event_type == "line_index_map_built":
                # Keep last values; also accumulate to totals in case of multi-pass
                last_line_index_map = {
                    "indexed_count": event.get("indexed_count"),
                    "missing_global_idx": event.get("missing_global_idx"),
                }
                line_index_indexed_total += int(event.get("indexed_count") or 0)
                line_index_missing_total += int(event.get("missing_global_idx") or 0)

            elif event_type == "header_missing_global":
                header_missing_global += 1

            elif event_type == "header_not_in_lines":
                header_not_in_lines += 1

            elif event_type == "chunk_bounds_resolved":
                chunk_bounds_resolved += 1

            elif event_type == "chunk_skipped_inverted":
                chunk_skipped_inverted += 1

            elif event_type == "chunk_built":
                built_chunks.append(
                    {
                        "position": event.get("position"),
                        "header_text": event.get("header_text"),
                        "header_number": event.get("header_number"),
                        "level": event.get("level"),
                        "start_global_idx": event.get("start_global_idx"),
                        "end_global_idx": event.get("end_global_idx"),
                        "start_page": event.get("start_page"),
                        "end_page": event.get("end_page"),
                        "line_count": event.get("line_count"),
                    }
                )

            elif event_type == "chunking_complete":
                chunking_completes += 1

            # --- Decision list collection
            if event_type in decision_types:
                decisions.append(event)

        chunking_summary = {
            "passes": chunking_passes,
            "completes": chunking_completes,
            "bounds_resolved": chunk_bounds_resolved,
            "skipped_inverted": chunk_skipped_inverted,
            "headers_missing_global": header_missing_global,
            "headers_not_in_lines": header_not_in_lines,
            "line_index_map": last_line_index_map,
            "line_index_map_totals": {
                "indexed_count": line_index_indexed_total,
                "missing_global_idx": line_index_missing_total,
            },
            "chunks": built_chunks,  # ordered by emission (construction order)
        }

        return {
            "trace_schema": "v2-chunking",
            "run_id": self.run_id,
            "metadata": metadata,
            "llm_headers": llm_headers,
            "llm_requests": llm_requests,
            "llm_raw_responses": llm_raw_responses,
            "llm_fenced_blocks": llm_fenced_blocks,
            "decisions": decisions,
            "chunking": chunking_summary,
            "final_outline": final_outline,
            "elapsed_s": elapsed,
            "function_calls": function_calls,
        }


__all__ = ["HeaderTracer", "TraceEvent"]
