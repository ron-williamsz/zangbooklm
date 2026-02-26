"""Upload e listagem de fontes (sources)."""
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import get_db
from app.schemas.source import SourceResponse
from app.services.source_service import SourceService

router = APIRouter(prefix="/sessions/{session_id}/sources", tags=["Sources"])


def _svc(db: AsyncSession = Depends(get_db)) -> SourceService:
    return SourceService(db)


@router.get("", response_model=list[SourceResponse])
async def list_sources(session_id: int, svc: SourceService = Depends(_svc)):
    return await svc.list_by_session(session_id)


@router.post("/upload", response_model=SourceResponse, status_code=201)
async def upload_source(
    session_id: int,
    file: UploadFile = File(...),
    svc: SourceService = Depends(_svc),
):
    return await svc.upload(session_id, file)


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    session_id: int, source_id: int, svc: SourceService = Depends(_svc)
):
    await svc.delete(session_id, source_id)
