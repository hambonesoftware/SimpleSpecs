"""Health check API router."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Schema describing the health check payload."""

    ok: bool


router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service health status")
def read_health() -> HealthResponse:
    """Return a simple health check payload indicating the API is alive."""

    return HealthResponse(ok=True)


__all__ = ["router", "HealthResponse", "read_health"]
