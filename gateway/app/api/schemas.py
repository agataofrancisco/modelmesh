"""Schemas de pedido/resposta da API de administração e da inferência (compatível com OpenAI)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_TEAM_RE = r"^[a-z0-9][a-z0-9\-]{1,62}$"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = None


class ChatCompletionRequest(BaseModel):
    """Subconjunto suportado nesta change. Campos extra são ignorados (não reenviados)."""

    model_config = ConfigDict(extra="ignore")

    model: str = Field(min_length=1, max_length=120)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    response_format: dict[str, Any] | None = None
    stream: bool | None = None

    @field_validator("messages")
    @classmethod
    def _messages_have_content(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if all(message.content in (None, "", []) for message in value):
            raise ValueError("pelo menos uma mensagem deve ter conteúdo")
        return value


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_TEAM_RE)
    name: str = Field(min_length=1, max_length=200)


class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: str = Field(pattern=_TEAM_RE)
    name: str = Field(min_length=1, max_length=200)
    rpm_limit: int | None = Field(default=None, ge=1, le=1_000_000)
    tpm_limit: int | None = Field(default=None, ge=1, le=100_000_000)
    concurrency_limit: int | None = Field(default=None, ge=1, le=10_000)
    budget_usd: Decimal | None = Field(default=None, ge=0, le=10_000_000)
