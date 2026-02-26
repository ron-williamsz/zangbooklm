"""Chat com LLM (streaming via SSE)."""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.base import get_db
from app.schemas.chat import ChatMessage, ChatSkillRequest
from app.services.chat_service import ChatService, clear_session_cache

router = APIRouter(prefix="/sessions/{session_id}/chat", tags=["Chat"])


@router.post("")
async def send_message(
    session_id: int,
    data: ChatMessage,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    svc = ChatService(db, settings)
    return StreamingResponse(
        svc.chat_stream(session_id, data.message),
        media_type="text/event-stream",
    )


@router.post("/skill/{skill_id}")
async def execute_skill(
    session_id: int,
    skill_id: int,
    data: ChatSkillRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    svc = ChatService(db, settings)
    return StreamingResponse(
        svc.chat_with_skill(session_id, skill_id, data.message),
        media_type="text/event-stream",
    )


@router.get("/history")
async def get_history(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    svc = ChatService(db, settings)
    return await svc.get_history(session_id)


@router.delete("/cache", status_code=204)
async def reset_chat_cache(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Limpa histórico do chat no banco e cache em memória."""
    svc = ChatService(db, settings)
    await svc.clear_history(session_id)
