"""Inicialização do FastAPI — Notebook Zang."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.exception_handlers import register_handlers
from app.core.http_client import close_client, init_client
from app.models.base import init_db
from app.routers import chat, condominios, gosati, pages, sessions, skills, sources

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_client()
    await init_db()
    yield
    await close_client()


app = FastAPI(
    title="Notebook Zang",
    description="Notebook com Skills customizáveis para análise de dados",
    version="0.1.0",
    lifespan=lifespan,
)

register_handlers(app)

# Static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# API routes
app.include_router(skills.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(sources.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(gosati.router, prefix="/api/v1")
app.include_router(condominios.router, prefix="/api/v1")

# HTML pages
app.include_router(pages.router)


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}
