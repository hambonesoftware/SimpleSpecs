from __future__ import annotations

from typing import Any, Dict


class AlignmentPreconditionError(Exception):
    """Raised when preconditions for header alignment are not satisfied."""

    def __init__(self, code: str, message: str, extra: Dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.extra = extra or {}


class OutlineParseError(Exception):
    """Raised when an outline cannot be parsed from the LLM response."""

    def __init__(
        self,
        code: str,
        message: str,
        raw: str | None = None,
        extra: Dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.raw = raw
        self.extra = extra or {}
