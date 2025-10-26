"""Request metrics collection utilities."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Dict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


@dataclass
class RouteStats:
    """Mutable statistics for a single route."""

    count: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float | None = None
    max_duration_ms: float | None = None


class MetricsRegistry:
    """In-memory collector for lightweight request metrics."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._in_flight = 0
        self._requests_total = 0
        self._status_families: Counter[str] = Counter()
        self._routes: Dict[str, RouteStats] = {}

    def reset(self) -> None:
        """Reset all counters (useful for tests)."""

        with self._lock:
            self._in_flight = 0
            self._requests_total = 0
            self._status_families = Counter()
            self._routes = {}

    def request_started(self) -> None:
        """Mark the start of a request."""

        with self._lock:
            self._in_flight += 1

    def request_finished(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        """Record request completion statistics."""

        duration_ms = max(duration_seconds * 1000.0, 0.0)
        route_key = f"{method.upper()} {path}"
        status_family = f"{status_code // 100}xx"

        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._requests_total += 1
            self._status_families[status_family] += 1

            stats = self._routes.setdefault(route_key, RouteStats())
            stats.count += 1
            stats.total_duration_ms += duration_ms
            stats.min_duration_ms = (
                duration_ms
                if stats.min_duration_ms is None
                else min(stats.min_duration_ms, duration_ms)
            )
            stats.max_duration_ms = (
                duration_ms
                if stats.max_duration_ms is None
                else max(stats.max_duration_ms, duration_ms)
            )

    def snapshot(self) -> Dict[str, object]:
        """Return an immutable view of the current metrics."""

        with self._lock:
            routes: Dict[str, Dict[str, float | int | None]] = {}
            for key, stats in self._routes.items():
                count = stats.count or 1
                average = stats.total_duration_ms / count
                routes[key] = {
                    "count": stats.count,
                    "avg_duration_ms": average,
                    "min_duration_ms": stats.min_duration_ms,
                    "max_duration_ms": stats.max_duration_ms,
                }

            return {
                "requests_total": self._requests_total,
                "in_flight": self._in_flight,
                "status_codes": dict(self._status_families),
                "routes": routes,
            }


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that records request metrics."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        registry: MetricsRegistry | None = None,
    ) -> None:
        super().__init__(app)
        self._registry = registry or metrics_registry

    async def dispatch(self, request: Request, call_next):
        start = perf_counter()
        self._registry.request_started()
        try:
            response = await call_next(request)
        except Exception:  # pragma: no cover - re-raise after recording metrics
            duration = perf_counter() - start
            self._registry.request_finished(
                request.method, request.url.path, 500, duration
            )
            raise
        else:
            duration = perf_counter() - start
            self._registry.request_finished(
                request.method,
                request.url.path,
                getattr(response, "status_code", 200),
                duration,
            )
            return response


metrics_registry = MetricsRegistry()

__all__ = [
    "MetricsRegistry",
    "RequestMetricsMiddleware",
    "metrics_registry",
]
