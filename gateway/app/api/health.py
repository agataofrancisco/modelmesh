"""Health checks e métricas.

- `/health/live`: o processo responde. Não toca em dependências.
- `/health/ready`: Redis e Postgres acessíveis e pelo menos um hop com circuito fechado.
- `/metrics`: formato Prometheus. Deve ficar na rede privada (ver deploy/ e docs/architecture.md).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from gateway.app.policy.schemas import TeamPolicy
from gateway.app.providers.base import Hop
from gateway.app.store import repository

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request) -> JSONResponse:
    services = request.app.state.services
    checks: dict[str, Any] = {}
    healthy = True

    try:
        await services.redis.ping()
        checks["redis"] = "ok"
    except RedisError:
        checks["redis"] = "unavailable"
        healthy = False

    try:
        async with services.session_factory() as session:
            await session.execute(text("SELECT 1"))
            bodies = await repository.all_latest_policy_bodies(session)
        checks["postgres"] = "ok"
    except SQLAlchemyError:
        bodies = []
        checks["postgres"] = "unavailable"
        healthy = False

    hops = {
        (h.provider, h.model)
        for body in bodies
        for route in TeamPolicy.model_validate(body).models.values()
        for h in route.chain
    }
    if checks.get("redis") == "ok" and hops:
        closed = 0
        for provider, model in hops:
            if await services.breaker.state(Hop(provider=provider, model=model)) == "closed":
                closed += 1
        checks["providers_with_closed_circuit"] = closed
        if closed == 0:
            healthy = False
    else:
        checks["providers_with_closed_circuit"] = None

    status = 200 if healthy else 503
    return JSONResponse(
        {"status": "ok" if healthy else "unavailable", "checks": checks}, status_code=status
    )


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    body = request.app.state.services.metrics.render()
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)
