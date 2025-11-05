"""Structured tracing utilities for specification bucket runs."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping


LOGGER = logging.getLogger(__name__)


class SpecTracer:
    """Collect structured events for specification bucket executions."""

    def __init__(
        self,
        *,
        run_id: str | None = None,
        out_dir: str = "backend/logs/specs",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.run_id = run_id or str(uuid.uuid4())
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.out_dir / f"{self.run_id}.json"
        self._closed = False
        self._metadata: MutableMapping[str, Any] = dict(metadata or {})
        self._events: list[dict[str, Any]] = []
        self._started_at = time.time()
        LOGGER.debug("[specs] SpecTracer created", {"run_id": self.run_id, "path": str(self._path)})

    # ------------------------------------------------------------------
    def metadata(self, **fields: Any) -> None:
        """Attach metadata to the trace and emit a metadata event."""

        if not fields:
            return
        self._metadata.update({k: v for k, v in fields.items() if v is not None})
        self._record("metadata", **fields)

    def function_call(self, name: str, **context: Any) -> None:
        self._record("function_call", name=name, **context)

    def llm_request(self, *, bucket: str | None, request_headers: Mapping[str, Any], request_body: Mapping[str, Any]) -> None:
        self._record(
            "llm_request",
            bucket=bucket,
            headers=dict(request_headers),
            body=json.loads(json.dumps(request_body)),
        )

    def llm_response(
        self,
        *,
        bucket: str | None,
        status_code: int,
        response_headers: Mapping[str, Any],
        response_body: Mapping[str, Any] | list[Any] | str,
    ) -> None:
        try:
            serialisable_body = json.loads(json.dumps(response_body))
        except Exception:
            serialisable_body = response_body
        self._record(
            "llm_response",
            bucket=bucket,
            status_code=status_code,
            headers=dict(response_headers),
            body=serialisable_body,
        )

    def decision(self, name: str, **data: Any) -> None:
        self._record("decision", name=name, **data)

    def outcome(self, name: str, **data: Any) -> None:
        self._record("outcome", name=name, **data)

    def message(self, text: str, **data: Any) -> None:
        self._record("message", text=text, **data)

    # ------------------------------------------------------------------
    def flush(self) -> str:
        """Persist the trace to disk and return the path."""

        if self._closed:
            return str(self._path)

        finished_at = time.time()
        summary = self._build_summary(finished_at)
        with self._path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
        os.chmod(self._path, 0o600)
        self._closed = True
        LOGGER.info("[specs] Spec trace saved", {"run_id": self.run_id, "path": str(self._path)})
        return str(self._path)

    @property
    def path(self) -> str:
        return str(self._path)

    # ------------------------------------------------------------------
    def _record(self, event_type: str, **data: Any) -> None:
        payload = {"type": event_type, "ts": time.time(), **data}
        self._events.append(payload)

    def _build_summary(self, finished_at: float) -> Dict[str, Any]:
        started_dt = datetime.fromtimestamp(self._started_at, tz=timezone.utc)
        finished_dt = datetime.fromtimestamp(finished_at, tz=timezone.utc)
        events = [self._normalise_event(event) for event in self._events]

        summary: Dict[str, Any] = {
            "run_id": self.run_id,
            "metadata": dict(self._metadata),
            "started_at": started_dt.isoformat(),
            "finished_at": finished_dt.isoformat(),
            "duration_seconds": round(finished_at - self._started_at, 3),
            "function_calls": [self._strip_type(event) for event in events if event["type"] == "function_call"],
            "llm_requests": [self._strip_type(event) for event in events if event["type"] == "llm_request"],
            "llm_responses": [self._strip_type(event) for event in events if event["type"] == "llm_response"],
            "decisions": [self._strip_type(event) for event in events if event["type"] == "decision"],
            "outcomes": [self._strip_type(event) for event in events if event["type"] == "outcome"],
            "messages": [self._strip_type(event) for event in events if event["type"] == "message"],
            "events": events,
        }
        return summary

    @staticmethod
    def _normalise_event(event: Mapping[str, Any]) -> Dict[str, Any]:
        payload = dict(event)
        ts = payload.pop("ts", None)
        if ts is not None:
            payload["timestamp"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        return payload

    @staticmethod
    def _strip_type(event: Mapping[str, Any]) -> Dict[str, Any]:
        payload = dict(event)
        payload.pop("type", None)
        return payload


__all__ = ["SpecTracer"]
