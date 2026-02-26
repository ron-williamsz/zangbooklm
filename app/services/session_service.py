"""Serviço de gerenciamento de Sessions."""
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.exceptions import NotFoundError
from app.models.session import Session
from app.models.chat_message import ChatMessage as ChatMessageRecord
from app.schemas.session import SessionCreate
from app.services.chat_service import clear_session_cache

logger = logging.getLogger(__name__)


class SessionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[Session]:
        result = await self.db.execute(select(Session).order_by(Session.created_at.desc()))
        return result.scalars().all()

    async def get_by_id(self, session_id: int) -> Session:
        session = await self.db.get(Session, session_id)
        if not session:
            raise NotFoundError(404, f"Session {session_id} não encontrada")
        return session

    async def create(self, data: SessionCreate) -> Session:
        session = Session(**data.model_dump())
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def delete(self, session_id: int) -> None:
        session = await self.get_by_id(session_id)
        # Remove mensagens de chat associadas
        stmt = select(ChatMessageRecord).where(ChatMessageRecord.session_id == session_id)
        result = await self.db.execute(stmt)
        for msg in result.scalars().all():
            await self.db.delete(msg)
        await self.db.delete(session)
        await self.db.commit()
        # Limpa cache em memória
        clear_session_cache(session_id)
