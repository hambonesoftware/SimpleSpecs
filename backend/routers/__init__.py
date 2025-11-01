"""API router package."""

from fastapi import APIRouter

from .compare import router as compare_router
from .documents import router as documents_router
from .files import router as files_router
from .health import router as health_router
from .headers import router as headers_router
from .observability import router as observability_router
from .parse import router as parse_router
from .search import router as search_router
from .specs import router as specs_router

api_router = APIRouter()
api_router.include_router(files_router)
api_router.include_router(documents_router)
api_router.include_router(headers_router)
api_router.include_router(health_router)
api_router.include_router(parse_router)
api_router.include_router(specs_router)
api_router.include_router(compare_router)
api_router.include_router(observability_router)
api_router.include_router(search_router)

__all__ = ["api_router"]
