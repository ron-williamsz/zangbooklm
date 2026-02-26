"""Serviço de gerenciamento de Sessions."""
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.exceptions import NotFoundError
from app.models.session import Session
from app.schemas.session import SessionCreate

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
        await self.db.delete(session)
        await self.db.commit()
