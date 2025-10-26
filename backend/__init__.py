"""Backend package for SimpleSpecs."""

from __future__ import annotations

from functools import wraps
import sys

import python_multipart
import python_multipart.multipart

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Compatibility shim: Starlette currently imports the legacy ``multipart``
# package which emits a ``PendingDeprecationWarning``. Register the modern
# ``python_multipart`` modules under the legacy import paths so Starlette can
# resolve them without triggering the warning while we migrate.
# ---------------------------------------------------------------------------
sys.modules.setdefault("multipart", python_multipart)
sys.modules.setdefault("multipart.multipart", python_multipart.multipart)


def _patch_testclient() -> None:
    """Apply runtime fixes for FastAPI's synchronous test client."""

    try:
        from fastapi.testclient import TestClient
    except Exception:  # pragma: no cover - fastapi is an optional dependency
        return

    if getattr(
        TestClient, "_simplespecs_patch", False
    ):  # pragma: no cover - idempotent
        return

    original_exit = TestClient.__exit__
    original_wait_shutdown = TestClient.wait_shutdown

    @wraps(original_wait_shutdown)
    async def patched_wait_shutdown(self: TestClient, *args, **kwargs):
        try:
            await original_wait_shutdown(self, *args, **kwargs)
        finally:
            stream_receive = getattr(self, "stream_receive", None)
            if stream_receive is not None:
                try:
                    await stream_receive.aclose()
                except Exception:  # pragma: no cover - defensive cleanup
                    pass

    @wraps(original_exit)
    def patched_exit(self: TestClient, *args, **kwargs):
        try:
            return original_exit(self, *args, **kwargs)
        finally:
            for attr in ("stream_send", "stream_receive"):
                if hasattr(self, attr):
                    setattr(self, attr, None)

    TestClient.wait_shutdown = patched_wait_shutdown  # type: ignore[assignment]
    TestClient.__exit__ = patched_exit  # type: ignore[assignment]
    TestClient._simplespecs_patch = True  # type: ignore[attr-defined]


_patch_testclient()

__all__ = ["python_multipart", "__version__"]
