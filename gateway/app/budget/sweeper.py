"""Sweeper de reservas órfãs: reconcilia reservas cujo pedido morreu sem as libertar.

Cobra a estimativa (limite superior conservador) e grava um registo de uso com estado
`orphan_released`, para que o custo fique auditável. Corre em loop no lifespan da aplicação.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from gateway.app.accounting.prices import micro_to_usd
from gateway.app.container import Services
from gateway.app.store import repository

logger = logging.getLogger("modelmesh.sweeper")
EVENT_ORPHAN = "orphan_reservation_released"


async def sweep_once(services: Services, *, now_ms: int | None = None) -> int:
    now = services.clock.wall_ms() if now_ms is None else now_ms
    expired = await services.budget.expire_due(now)
    for payload in expired:
        await _record_orphan(services, payload)
        logger.warning(
            "%s",
            EVENT_ORPHAN,
            extra={"request_id": payload.get("request_id"), "team_id": payload.get("team_id")},
        )
    return len(expired)


async def _record_orphan(services: Services, payload: dict[str, Any]) -> None:
    estimate_micro = int(payload.get("estimate_micro", 0))
    record = {
        "request_id": str(payload.get("request_id", "unknown")),
        "team_id": str(payload.get("team_id", "unknown")),
        "key_id": payload.get("key_id"),
        "key_prefix": payload.get("key_prefix"),
        "model_requested": str(payload.get("model_requested", "unknown")),
        "model_served": None,
        "provider_served": None,
        "fallback_path": [],
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_estimated_usd": micro_to_usd(estimate_micro),
        "cost_real_usd": micro_to_usd(estimate_micro),
        "usage_estimated": True,
        "latency_ms": 0,
        "status": "orphan_released",
        "error_code": "orphan",
        "trace_id": payload.get("trace_id"),
    }
    async with services.session_factory() as session:
        await repository.insert_usage(session, record)


async def sweeper_loop(services: Services) -> None:  # pragma: no cover - loop de fundo
    while True:
        try:
            await sweep_once(services)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - o loop não pode morrer por um erro transitório
            logger.exception("falha no sweeper de reservas")
        await asyncio.sleep(services.settings.sweeper_interval_s)
