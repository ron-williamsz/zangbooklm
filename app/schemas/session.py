"""Schemas de request/response para Sessions."""
from datetime import datetime

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = Field(max_length=200)


class SessionResponse(BaseModel):
    id: int
    title: str
    active_skill_id: int | None
    source_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
