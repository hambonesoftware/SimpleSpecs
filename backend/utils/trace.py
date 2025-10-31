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
    """Collect structured events for header tracing."""

    def __init__(
        self, run_id: Optional[str] = None, out_dir: str = "backend/logs/headers"
    ) -> None:
        self.run_id = run_id or str(uuid.uuid4())
        self.out_dir = out_dir
        self.events: List[TraceEvent] = []
        os.makedirs(self.out_dir, exist_ok=True)
        self._path = os.path.join(self.out_dir, f"{self.run_id}.jsonl")
        self._summary_path = os.path.join(self.out_dir, f"{self.run_id}.summary.json")

    def ev(self, event_type: str, **data: Any) -> None:
        self.events.append(TraceEvent(t=time.time(), type=event_type, data=data))

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
        final_outline: Dict[str, Any] = {}
        decisions: List[Dict[str, Any]] = []
        elapsed: float | None = None

        decision_types = {
            "candidate_found",
            "anchor_resolved",
            "fallback_triggered",
            "monotonic_violation",
        }

        for event in events:
            event_type = event.get("type")
            if event_type == "start_run":
                metadata = {
                    key: value
                    for key, value in event.items()
                    if key not in {"t", "type"}
                }
            elif event_type == "llm_outline_received":
                llm_headers = list(event.get("headers", []))
            elif event_type == "final_outline":
                final_outline = {
                    "headers": list(event.get("headers", [])),
                    "sections": list(event.get("sections", [])),
                    "mode": event.get("mode"),
                    "messages": list(event.get("messages", [])),
                }
                if "elapsed_s" in event:
                    elapsed = event.get("elapsed_s")
            elif event_type == "end_run":
                if elapsed is None:
                    elapsed = event.get("elapsed_s")
                final_outline.setdefault("mode", event.get("mode"))

            if event_type in decision_types:
                decisions.append(event)

        return {
            "run_id": self.run_id,
            "metadata": metadata,
            "llm_headers": llm_headers,
            "decisions": decisions,
            "final_outline": final_outline,
            "elapsed_s": elapsed,
        }


__all__ = ["HeaderTracer", "TraceEvent"]
