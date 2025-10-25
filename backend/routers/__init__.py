"""API router package."""
from fastapi import APIRouter

from .files import router as files_router

api_router = APIRouter()
api_router.include_router(files_router)

__all__ = ["api_router"]
