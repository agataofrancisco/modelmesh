"""Interface de adaptador de provider e taxonomia de erros.

A taxonomia é o contrato entre os adaptadores e o policy engine: o engine decide retries e
fallback só com base na `kind`, nunca com base em strings de erro de um provider concreto.

| kind               | retry no mesmo hop | fallback | conta para o circuito |
|--------------------|--------------------|----------|-----------------------|
| transient          | sim                | sim      | sim                   |
| timeout            | sim                | sim      | sim                   |
| auth               | não                | sim      | sim                   |
| invalid_response   | não                | sim      | sim                   |
| client             | não                | não      | não                   |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

KIND_TRANSIENT = "transient"
KIND_TIMEOUT = "timeout"
KIND_AUTH = "auth"
KIND_INVALID = "invalid_response"
KIND_CLIENT = "client"

RETRYABLE_KINDS = frozenset({KIND_TRANSIENT, KIND_TIMEOUT})
FALLBACK_KINDS = frozenset({KIND_TRANSIENT, KIND_TIMEOUT, KIND_AUTH, KIND_INVALID})
CIRCUIT_FAILURE_KINDS = frozenset({KIND_TRANSIENT, KIND_TIMEOUT, KIND_AUTH, KIND_INVALID})


class ProviderError(Exception):
    """Falha normalizada de um provider. `message` é interna e nunca vai para o cliente."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        status: int | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        self.kind = kind
        self.status = status
        self.retry_after_s = retry_after_s
        super().__init__(message)

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_KINDS

    @property
    def fallback_eligible(self) -> bool:
        return self.kind in FALLBACK_KINDS


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class ProviderResponse:
    body: dict[str, Any]
    usage: Usage | None
    raw_model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Hop:
    provider: str
    model: str


class ProviderAdapter(Protocol):
    async def chat(
        self, hop: Hop, body: dict[str, Any], *, timeout_s: float
    ) -> ProviderResponse:  # pragma: no cover - interface
        """Envia o pedido ao provider. Levanta `ProviderError` em qualquer falha."""
        ...
