"""Backend package for SimpleSpecs."""
from __future__ import annotations

import sys

import python_multipart
import python_multipart.multipart

# ---------------------------------------------------------------------------
# Compatibility shim: Starlette currently imports the legacy ``multipart``
# package which emits a ``PendingDeprecationWarning``. Register the modern
# ``python_multipart`` modules under the legacy import paths so Starlette can
# resolve them without triggering the warning while we migrate.
# ---------------------------------------------------------------------------
sys.modules.setdefault("multipart", python_multipart)
sys.modules.setdefault("multipart.multipart", python_multipart.multipart)

__all__ = ["python_multipart"]
