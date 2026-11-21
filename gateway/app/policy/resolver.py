"""Resolução de rota: modelo pedido (ou alias de classe) -> modelo concreto e cadeia de hops.

Função pura: sem I/O. Recebe a política já validada e devolve a decisão explicável que o gateway
expõe em cabeçalhos e no registo de uso.
"""

from __future__ import annotations

from dataclasses import dataclass

from gateway.app.errors import GatewayError
from gateway.app.policy.schemas import CLASS_NAMES, HopSpec, TeamPolicy


@dataclass(frozen=True)
class ResolvedRoute:
    requested_model: str
    served_model: str  # modelo concreto escolhido pela política
    via_class: str | None
    chain: tuple[HopSpec, ...]  # já limitada a max_hops
    max_tokens: int


def resolve_route(policy: TeamPolicy, requested: str) -> ResolvedRoute:
    if not isinstance(requested, str) or not requested:
        raise GatewayError("invalid_request", "campo model em falta")

    if requested in CLASS_NAMES:
        target = policy.classes.get(requested)  # type: ignore[arg-type]
        if target is None:
            raise GatewayError(
                "model_not_allowed",
                f"a equipa não tem modelo para a classe '{requested}'",
            )
        route = policy.models[target]
        return ResolvedRoute(
            requested_model=requested,
            served_model=target,
            via_class=requested,
            chain=tuple(route.chain[: policy.max_hops]),
            max_tokens=policy.max_tokens,
        )

    route = policy.models.get(requested)
    if route is None:
        raise GatewayError("model_not_allowed", "modelo não permitido para esta equipa")
    return ResolvedRoute(
        requested_model=requested,
        served_model=requested,
        via_class=None,
        chain=tuple(route.chain[: policy.max_hops]),
        max_tokens=policy.max_tokens,
    )
