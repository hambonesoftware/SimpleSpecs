"""File upload and listing endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlmodel import Session

from ..config import Settings, get_settings
from ..database import get_session
from ..models import Document
from ..services.files import handle_upload, list_documents

router = APIRouter(prefix="/api", tags=["files"])


@router.post("/upload", response_model=Document)
async def upload_file(
    *,
    file: UploadFile = File(...),
    response: Response,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Document:
    """Handle PDF uploads and return the stored document."""

    document, created = await handle_upload(session=session, upload=file, settings=settings)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return document


@router.get("/files", response_model=list[Document])
async def get_files(*, session: Session = Depends(get_session)) -> list[Document]:
    """Return the list of uploaded documents."""

    return list_documents(session=session)
