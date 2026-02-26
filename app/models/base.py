"""Database engine e inicialização com SQLModel async."""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.core.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Cria todas as tabelas no banco."""
    from app.models import Skill, SkillStep, SkillExample, Session, Source, ChatMessage  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_db() -> AsyncSession:
    """Dependency do FastAPI — fornece sessão do banco."""
    async with async_session_maker() as session:
        yield session
