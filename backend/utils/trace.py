from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class TraceEvent:
    t: float
    type: str
    data: Dict[str, Any]


class HeaderTracer:
    """Collect structured events for header tracing."""

    def __init__(self, run_id: Optional[str] = None, out_dir: str = "backend/logs/headers") -> None:
        self.run_id = run_id or str(uuid.uuid4())
        self.out_dir = out_dir
        self.events: List[TraceEvent] = []
        os.makedirs(self.out_dir, exist_ok=True)
        self._path = os.path.join(self.out_dir, f"{self.run_id}.jsonl")

    def ev(self, event_type: str, **data: Any) -> None:
        self.events.append(TraceEvent(t=time.time(), type=event_type, data=data))

    def flush_jsonl(self) -> str:
        with open(self._path, "w", encoding="utf-8") as handle:
            for event in self.events:
                payload = {"t": event.t, "type": event.type, **event.data}
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return self._path

    @property
    def path(self) -> str:
        return self._path

    def as_list(self) -> List[Dict[str, Any]]:
        return [{"t": event.t, "type": event.type, **event.data} for event in self.events]


__all__ = ["HeaderTracer", "TraceEvent"]
