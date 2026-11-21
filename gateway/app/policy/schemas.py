"""Política declarativa por equipa, validada antes de ser aplicada (`PUT /admin/policies/{team}`).

Modelo:
- `models`: modelos concretos que a equipa pode usar, cada um com a sua cadeia ordenada de
  `(provider, modelo)`. A cadeia é a ordem de fallback.
- `classes`: alias de classe (`cheap`, `balanced`, `critical`) para um modelo permitido.
- limites de tokens, hops, retries, timeouts e limites de tráfego/orçamento da equipa.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CLASS_NAMES = ("cheap", "balanced", "critical")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._\-]{0,63}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,119}$")


class HopSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=120)

    @field_validator("provider")
    @classmethod
    def _provider_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError("nome de provider inválido")
        return value

    @field_validator("model")
    @classmethod
    def _model_name(cls, value: str) -> str:
        if not _MODEL_RE.match(value):
            raise ValueError("nome de modelo inválido")
        return value


class ModelRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain: list[HopSpec] = Field(min_length=1, max_length=5)


class TeamPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: dict[str, ModelRoute] = Field(min_length=1, max_length=50)
    classes: dict[Literal["cheap", "balanced", "critical"], str] = Field(default_factory=dict)
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    max_hops: int = Field(default=2, ge=1, le=5)
    retries_per_hop: int = Field(default=1, ge=0, le=3)
    timeout_ms: int = Field(default=10_000, ge=100, le=120_000)
    hop_timeout_ms: int = Field(default=3_000, ge=50, le=120_000)
    rpm: int = Field(default=0, ge=0, le=1_000_000)
    tpm: int = Field(default=0, ge=0, le=100_000_000)
    concurrency: int = Field(default=0, ge=0, le=10_000)
    budget_usd_monthly: Decimal | None = Field(default=None, ge=0, le=10_000_000)

    @field_validator("models")
    @classmethod
    def _model_keys(cls, value: dict[str, ModelRoute]) -> dict[str, ModelRoute]:
        for name in value:
            if name in CLASS_NAMES:
                raise ValueError(f"'{name}' é um alias de classe e não um modelo")
            if not _MODEL_RE.match(name):
                raise ValueError(f"nome de modelo inválido: {name!r}")
        return value

    @model_validator(mode="after")
    def _cross_checks(self) -> TeamPolicy:
        for cls_name, target in self.classes.items():
            if target not in self.models:
                raise ValueError(f"classe '{cls_name}' aponta para modelo não permitido: {target}")
        if self.hop_timeout_ms > self.timeout_ms:
            raise ValueError("hop_timeout_ms não pode ser superior a timeout_ms")
        return self

    def provider_refs(self) -> set[str]:
        return {hop.provider for route in self.models.values() for hop in route.chain}
