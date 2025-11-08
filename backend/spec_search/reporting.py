"""Reporting utilities for the spec-search pipeline."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from backend.config import PROJECT_ROOT


def _utcnow() -> str:
    """Return an ISO8601 timestamp in UTC."""

    return datetime.now(timezone.utc).isoformat()


class SpecSearchReporter:
    """Persist a step-by-step report for spec-search runs."""

    def __init__(
        self,
        *,
        base_dir: Path | str | None = None,
        request_id: Optional[str] = None,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self._path: Optional[Path]
        self._public_path: Optional[str]
        if not enabled:
            self._path = None
            self._public_path = None
            return

        directory = Path(base_dir) if base_dir is not None else Path("backend/logs/spec_search")
        if not directory.is_absolute():
            directory = PROJECT_ROOT / directory
        directory.mkdir(parents=True, exist_ok=True)

        self._path = directory / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{request_id or uuid4().hex}.jsonl"
        try:
            public_path = str(self._path.relative_to(PROJECT_ROOT))
        except ValueError:
            public_path = str(self._path)

        self._public_path = public_path

    @classmethod
    def disabled(cls) -> "SpecSearchReporter":
        """Return a reporter instance that drops all events."""

        return cls(enabled=False)

    @property
    def log_path(self) -> Optional[str]:
        if not self.enabled or self._public_path is None:
            return None
        return self._public_path

    def _append(self, payload: Dict[str, Any]) -> None:
        if not self.enabled or self._path is None:
            return
        entry = json.dumps(payload, ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(entry)
            handle.write("\n")

    def log(self, event: str, **details: Any) -> None:
        """Record an intermediate event."""

        if not self.enabled or self._path is None:
            return
        payload: Dict[str, Any] = {
            "timestamp": _utcnow(),
            "event": event,
        }
        if details:
            payload["details"] = details
        self._append(payload)

    def finalize(self, status: str, **details: Any) -> Optional[str]:
        """Record the terminal state and return the public log path."""

        if not self.enabled or self._path is None:
            return None
        payload: Dict[str, Any] = {
            "timestamp": _utcnow(),
            "event": "pipeline.complete",
            "details": {"status": status, **details},
        }
        self._append(payload)
        return self._public_path


__all__ = ["SpecSearchReporter"]
