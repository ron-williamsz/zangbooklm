"""Schemas de request/response para Chat."""
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    message: str = Field(min_length=1)


class ChatSkillRequest(BaseModel):
    message: str = Field(
        default="Execute a skill sobre os documentos carregados.",
        min_length=1,
    )
