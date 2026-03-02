"""Integração GoSATI — consultas como fonte de dados."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.base import get_db
from app.models.session import Session
from app.schemas.gosati import (
    ComprovantesDownloadRequest,
    ComprovantesDownloadResponse,
    ComprovantesListRequest,
    ComprovantesListResponse,
    DespesaComprovante,
    GoSatiQuery,
    GoSatiSourceResponse,
)
from app.services.chat_service import ChatService
from app.services.gosati_service import GoSatiError, GoSatiService
from app.services.source_service import SourceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions/{session_id}/gosati", tags=["GoSATI"])

# Cache em memória da prestação de contas (para listar comprovantes sem refazer SOAP)
_prestacao_cache: dict[str, dict] = {}


@router.post("/source", response_model=GoSatiSourceResponse)
async def add_gosati_source(
    session_id: int,
    data: GoSatiQuery,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Consulta SOAP no GoSATI e salva resultado como Source do notebook."""
    # Detecta troca de condomínio — limpa sources GoSATI + chat antigos
    session = await db.get(Session, session_id)
    old_cond = session.gosati_condominio_codigo if session else None
    if old_cond and old_cond != data.condominio:
        logger.info(
            "Sessão %d: condomínio mudou de %s → %s, limpando dados antigos",
            session_id, old_cond, data.condominio,
        )
        source_svc = SourceService(db)
        await source_svc.delete_by_origin(session_id, "gosati")
        chat_svc = ChatService(db, settings)
        await chat_svc.clear_history(session_id)

    svc = GoSatiService(db, settings)
    try:
        source = await svc.query_as_source(
            session_id=session_id,
            query_type=data.query_type,
            condominio=data.condominio,
            mes=data.mes,
            ano=data.ano,
        )
    except GoSatiError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Cache para comprovantes (se prestação de contas)
    if data.query_type == "prestacao_contas" and hasattr(source, "_prestacao_data"):
        cache_key = f"{data.condominio}_{data.mes}_{data.ano}"
        _prestacao_cache[cache_key] = source._prestacao_data

    return GoSatiSourceResponse(
        source_id=source.id,
        label=source.label,
        query_type=data.query_type,
        size=source.size_bytes,
    )


@router.post("/comprovantes", response_model=ComprovantesListResponse)
async def list_comprovantes(
    session_id: int,
    data: ComprovantesListRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Lista despesas que possuem comprovantes disponíveis para download."""
    svc = GoSatiService(db, settings)

    cache_key = f"{data.condominio}_{data.mes}_{data.ano}"
    prestacao_data = _prestacao_cache.get(cache_key)

    if not prestacao_data:
        try:
            prestacao_data = await svc.consultar_prestacao_contas(
                data.condominio, data.mes, data.ano
            )
        except GoSatiError as e:
            raise HTTPException(status_code=502, detail=str(e))

        if not prestacao_data:
            raise HTTPException(
                status_code=404,
                detail="Nenhum dado de prestação de contas encontrado.",
            )
        _prestacao_cache[cache_key] = prestacao_data

    despesas = svc.extrair_despesas_com_comprovante(prestacao_data)
    items = [DespesaComprovante(**d) for d in despesas]

    return ComprovantesListResponse(despesas=items, total=len(items))


@router.post("/comprovantes/download", response_model=ComprovantesDownloadResponse)
async def download_comprovantes(
    session_id: int,
    data: ComprovantesDownloadRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Baixa comprovantes selecionados e salva como Sources do notebook."""
    svc = GoSatiService(db, settings)

    # Suporte ao novo formato (despesas com info do lançamento) e legado (links)
    if data.despesas:
        links = [d.link_docto for d in data.despesas]
        despesas_info = [
            {"numero_lancamento": d.numero_lancamento, "historico": d.historico, "valor": d.valor}
            for d in data.despesas
        ]
    else:
        links = data.links
        despesas_info = None

    try:
        sources = await svc.save_comprovantes_as_sources(
            session_id, links, despesas_info=despesas_info
        )
    except GoSatiError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return ComprovantesDownloadResponse(
        downloaded=len(sources),
        source_ids=[s.id for s in sources],
    )


@router.delete("/reset", status_code=204)
async def reset_gosati(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Remove todas as sources GoSATI da sessão, limpa chat e caches."""
    source_svc = SourceService(db)
    await source_svc.delete_by_origin(session_id, "gosati")
    # Limpa chat history do banco + caches em memória
    chat_svc = ChatService(db, settings)
    await chat_svc.clear_history(session_id)
    # Limpa cache de prestação
    keys_to_remove = [k for k in _prestacao_cache if True]  # limpa tudo por segurança
    for k in keys_to_remove:
        _prestacao_cache.pop(k, None)
