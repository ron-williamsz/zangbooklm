"""Serviço de chat com Gemini — integra Skills e Sources."""
import json
import logging
from collections import defaultdict
from typing import AsyncGenerator

from google import genai
from google.genai.types import Content, Part
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.services.skill_service import SkillService
from app.services.source_service import SourceService

logger = logging.getLogger(__name__)

# Cache em memória (por session)
_chat_histories: dict[int, list[Content]] = defaultdict(list)
_document_cache: dict[int, dict[int, dict]] = defaultdict(dict)
_sent_docs: dict[int, set[int]] = defaultdict(set)  # docs já enviados ao Gemini

# Limite de binários (imagens) enviados por turno ao Gemini
MAX_BINARY_BYTES_PER_TURN = 15 * 1024 * 1024  # 15 MB
MAX_BINARY_FILES_PER_TURN = 30


def clear_session_cache(session_id: int) -> None:
    """Limpa todo o cache em memória de uma sessão (histórico, docs, sent)."""
    _chat_histories.pop(session_id, None)
    _document_cache.pop(session_id, None)
    _sent_docs.pop(session_id, None)
    logger.info("Cache limpo para sessão %d", session_id)


class ChatService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings
        self.skill_svc = SkillService(db)
        self.source_svc = SourceService(db)

    async def chat_stream(
        self, session_id: int, message: str
    ) -> AsyncGenerator[str, None]:
        """Chat livre (sem skill ativa)."""
        async for chunk in self._generate(session_id, message, skill_id=None):
            yield chunk

    async def chat_with_skill(
        self, session_id: int, skill_id: int, message: str
    ) -> AsyncGenerator[str, None]:
        """Chat com skill ativa — injeta prompt da skill."""
        async for chunk in self._generate(session_id, message, skill_id=skill_id):
            yield chunk

    async def _generate(
        self, session_id: int, message: str, skill_id: int | None
    ) -> AsyncGenerator[str, None]:
        """Gera resposta via Gemini com streaming."""
        # Monta system instruction
        system_instruction = "Você é um assistente especializado em análise de dados."
        if skill_id:
            skill_prompt = await self.skill_svc.build_prompt(skill_id)
            system_instruction = skill_prompt

        # Carrega documentos da sessão (usa get_content_for_llm para conversão)
        sources = await self.source_svc.list_by_session(session_id)
        for src in sources:
            if src.id not in _document_cache.get(session_id, {}):
                try:
                    content, mime_type = self.source_svc.get_content_for_llm(src)
                    _document_cache[session_id][src.id] = {
                        "content": content,
                        "mime_type": mime_type,
                        "filename": src.filename,
                    }
                except Exception as e:
                    logger.warning(f"Erro ao ler source {src.id}: {e}")

        # Monta partes dos documentos que ainda não foram enviados
        # Separa texto (leve) de binário (pesado) e aplica limites
        doc_parts = []
        text_docs = []
        binary_docs = []
        for src_id, doc in _document_cache.get(session_id, {}).items():
            if src_id not in _sent_docs.get(session_id, set()):
                if isinstance(doc["content"], bytes):
                    binary_docs.append((src_id, doc))
                else:
                    text_docs.append((src_id, doc))

        # Texto sempre vai (leve)
        for src_id, doc in text_docs:
            doc_parts.append(Part(text=f"[Documento: {doc['filename']}]\n{doc['content']}"))
            _sent_docs[session_id].add(src_id)

        # Binários com limite de tamanho e quantidade
        binary_total = 0
        binary_count = 0
        skipped = 0
        for src_id, doc in binary_docs:
            size = len(doc["content"])
            if (binary_total + size > MAX_BINARY_BYTES_PER_TURN
                    or binary_count >= MAX_BINARY_FILES_PER_TURN):
                skipped += 1
                _sent_docs[session_id].add(src_id)  # marca como "enviado" para não ficar preso
                continue
            doc_parts.append(Part.from_bytes(data=doc["content"], mime_type=doc["mime_type"]))
            binary_total += size
            binary_count += 1
            _sent_docs[session_id].add(src_id)

        if skipped:
            doc_parts.append(Part(text=f"[Nota: {skipped} arquivo(s) binário(s) omitidos por limite de tamanho]"))
            logger.warning("Sessão %d: %d binários omitidos (limite %d MB)", session_id, skipped, MAX_BINARY_BYTES_PER_TURN // (1024*1024))

        # Monta mensagem do usuário com docs novos
        user_parts = doc_parts + [Part(text=message)]
        _chat_histories[session_id].append(
            Content(role="user", parts=user_parts)
        )

        try:
            client = genai.Client(
                vertexai=True,
                project=self.settings.gcp_project_id,
                location=self.settings.gemini_location,
            )

            response = client.models.generate_content_stream(
                model=self.settings.gemini_model,
                contents=_chat_histories[session_id],
                config={
                    "system_instruction": system_instruction,
                    "temperature": self.settings.gemini_temperature,
                    "max_output_tokens": self.settings.gemini_max_output_tokens,
                },
            )

            full_response = ""
            for chunk in response:
                if chunk.text:
                    full_response += chunk.text
                    yield f"data: {json.dumps({'text': chunk.text})}\n\n"

            # Salva resposta no histórico
            _chat_histories[session_id].append(
                Content(role="model", parts=[Part(text=full_response)])
            )
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Erro no Gemini: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    def get_history(self, session_id: int) -> list[dict]:
        """Retorna histórico do chat."""
        history = []
        for content in _chat_histories.get(session_id, []):
            history.append({
                "role": content.role,
                "text": content.parts[0].text if content.parts else "",
            })
        return history
