"""Health check endpoint."""

from fastapi import APIRouter

router = APIRouter()


async def _health_payload() -> dict[str, str]:
    """Shared response payload for health checks."""

    return {"status": "ok"}


@router.get("/health", summary="Health check")
async def health() -> dict[str, str]:
    """Return service health information."""

    return await _health_payload()


@router.get("/healthz", summary="Legacy health check")
async def healthz() -> dict[str, str]:
    """Return service health information (legacy endpoint)."""

    return await _health_payload()
