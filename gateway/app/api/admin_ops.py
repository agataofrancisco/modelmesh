"""Administração operacional: uso, orçamentos, rotas efectivas, circuitos e controlo dos mocks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from gateway.app.accounting.prices import micro_to_usd
from gateway.app.auth.dependencies import require_admin
from gateway.app.budget.ledger import current_period
from gateway.app.errors import GatewayError
from gateway.app.policy.resolver import resolve_route
from gateway.app.policy.schemas import CLASS_NAMES, TeamPolicy
from gateway.app.providers.base import Hop
from gateway.app.store import repository

router = APIRouter(prefix="/admin", tags=["admin-ops"], dependencies=[Depends(require_admin)])


@router.get("/usage")
async def usage(
    request: Request,
    group_by: Literal["team", "key", "model"] = "team",
    team: str | None = None,
    key_prefix: str | None = None,
    model: str | None = None,
    days: int = 7,
) -> dict[str, Any]:
    if days < 1 or days > 366:
        raise GatewayError("validation_error", "days deve estar entre 1 e 366")
    since = datetime.now(UTC) - timedelta(days=days)
    async with request.app.state.services.session_factory() as session:
        rows = await repository.usage_aggregate(
            session,
            group_by=group_by,
            team_id=team,
            key_prefix=key_prefix,
            model=model,
            since=since,
        )
    return {"group_by": group_by, "since": since.isoformat(), "data": rows}


@router.get("/budgets")
async def budgets(request: Request, team: str) -> dict[str, Any]:
    services = request.app.state.services
    async with services.session_factory() as session:
        row = await repository.latest_policy(session, team)
    if row is None:
        raise GatewayError("not_found", "equipa sem política")
    policy = TeamPolicy.model_validate(row.body)
    period = current_period(services.clock.wall_ms())
    snapshot = await services.budget.snapshot(f"team:{team}", period)
    limit = policy.budget_usd_monthly
    return {
        "team_id": team,
        "period": period,
        "budget_usd_monthly": str(limit) if limit is not None else None,
        "spent_usd": str(micro_to_usd(snapshot["spent_micro"])),
        "reserved_usd": str(micro_to_usd(snapshot["reserved_micro"])),
    }


@router.get("/routes")
async def routes(request: Request, team: str) -> dict[str, Any]:
    """Resolução efectiva por equipa: cada modelo permitido e cada classe, com a cadeia."""
    async with request.app.state.services.session_factory() as session:
        row = await repository.latest_policy(session, team)
    if row is None:
        raise GatewayError("not_found", "equipa sem política")
    policy = TeamPolicy.model_validate(row.body)
    entries = []
    for name in list(policy.models) + list(CLASS_NAMES):
        try:
            route = resolve_route(policy, name)
        except GatewayError:
            continue  # classe sem modelo associado: não é uma rota
        entries.append(
            {
                "requested": name,
                "served_model": route.served_model,
                "via_class": route.via_class,
                "chain": [{"provider": h.provider, "model": h.model} for h in route.chain],
                "max_tokens": route.max_tokens,
            }
        )
    return {"team_id": team, "version": row.version, "routes": entries}


@router.get("/circuits")
async def circuits(request: Request) -> dict[str, Any]:
    services = request.app.state.services
    async with services.session_factory() as session:
        policies = await repository.all_latest_policy_bodies(session)
    seen: set[tuple[str, str]] = set()
    for body in policies:
        policy = TeamPolicy.model_validate(body)
        for route in policy.models.values():
            for hop in route.chain:
                seen.add((hop.provider, hop.model))
    data = []
    for provider, model in sorted(seen):
        state = await services.breaker.state(Hop(provider=provider, model=model))
        data.append({"provider": provider, "model": model, "state": state})
    return {"data": data}


@router.put("/mocks/{name}/profile")
async def mock_profile(request: Request, name: str) -> JSONResponse:
    """Encaminha a configuração de falhas para o mock (usado pelo testador de failover)."""
    services = request.app.state.services
    config = services.settings.providers.get(name)
    if config is None or not config.control_url:
        raise GatewayError("not_found", "mock sem endpoint de controlo")
    try:
        payload = await request.json()
    except ValueError as exc:
        raise GatewayError("invalid_request", "corpo JSON inválido") from exc
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            upstream = await client.put(f"{config.control_url}/control/profile", json=payload)
    except httpx.HTTPError as exc:
        raise GatewayError("upstream_unavailable", "mock inacessível") from exc
    return JSONResponse(upstream.json(), status_code=upstream.status_code)
