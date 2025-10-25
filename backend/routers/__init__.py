"""API router package."""
from fastapi import APIRouter

from .files import router as files_router
from .parse import router as parse_router

api_router = APIRouter()
api_router.include_router(files_router)
api_router.include_router(parse_router)

__all__ = ["api_router"]
