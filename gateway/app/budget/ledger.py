"""Orçamentos: reserva antes do pedido, reconciliação depois, sweeper de órfãs.

Redis guarda os contadores quentes (spent/reserved por âmbito e período) e as reservas.
Postgres (`usage_records`) é a fonte de verdade: `rebuild_spent` reconstrói os contadores a
partir dele no arranque. Ver docs/learn/07-orcamentos-reserva-reconciliacao.md.

Unidades: micro-USD inteiros. Período: mês UTC (`YYYYMM`).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from redis.asyncio import Redis

from gateway.app.limits.rate_limiter import load_lua

LUA_DIR = Path(__file__).resolve().parent / "lua"
PENDING_KEY = "resv:pending"


class BudgetExceeded(Exception):
    def __init__(self, scope: str) -> None:
        self.scope = scope  # "key" ou "team"
        super().__init__(f"budget exceeded ({scope})")


@dataclass(frozen=True)
class BudgetScope:
    scope_id: str  # "key:<id>" ou "team:<id>"
    budget_micro: int  # -1 = sem limite


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    period: str
    key_scope: str
    team_scope: str
    estimate_micro: int
    payload: dict[str, Any]


def current_period(now_ms: int) -> str:
    return datetime.fromtimestamp(now_ms / 1000, tz=UTC).strftime("%Y%m")


def _counter_names(scope_id: str, period: str) -> tuple[str, str]:
    base = f"bud:{scope_id}:{period}"
    return f"{base}:spent", f"{base}:reserved"


class BudgetLedger:
    def __init__(self, redis: Redis, *, reservation_ttl_s: int) -> None:
        self._redis = redis
        self._ttl_ms = reservation_ttl_s * 1000
        self._reserve = redis.register_script(load_lua("reserve.lua", LUA_DIR))
        self._settle = redis.register_script(load_lua("settle.lua", LUA_DIR))

    async def reserve(
        self,
        key_scope: BudgetScope,
        team_scope: BudgetScope,
        *,
        estimate_micro: int,
        now_ms: int,
        payload: dict[str, Any],
    ) -> Reservation:
        if estimate_micro < 0:
            raise ValueError("estimativa negativa")
        period = current_period(now_ms)
        key_spent, key_reserved = _counter_names(key_scope.scope_id, period)
        team_spent, team_reserved = _counter_names(team_scope.scope_id, period)
        reservation_id = uuid.uuid4().hex
        body = dict(payload)
        body.update(
            {
                "reservation_id": reservation_id,
                "period": period,
                "key_scope": key_scope.scope_id,
                "team_scope": team_scope.scope_id,
                "estimate_micro": estimate_micro,
                "reserved_at_ms": now_ms,
            }
        )
        result = await self._reserve(
            keys=[
                key_spent,
                key_reserved,
                team_spent,
                team_reserved,
                f"resv:{reservation_id}",
                PENDING_KEY,
            ],
            args=[
                key_scope.budget_micro,
                team_scope.budget_micro,
                estimate_micro,
                now_ms + self._ttl_ms,
                reservation_id,
                json.dumps(body),
            ],
        )
        code = int(result)
        if code == 1:
            raise BudgetExceeded("key")
        if code == 2:
            raise BudgetExceeded("team")
        return Reservation(
            reservation_id=reservation_id,
            period=period,
            key_scope=key_scope.scope_id,
            team_scope=team_scope.scope_id,
            estimate_micro=estimate_micro,
            payload=body,
        )

    async def settle(self, reservation: Reservation, *, real_micro: int) -> bool:
        """Substitui a reserva pelo custo real. Devolve False se a reserva já não existia."""
        key_spent, key_reserved = _counter_names(reservation.key_scope, reservation.period)
        team_spent, team_reserved = _counter_names(reservation.team_scope, reservation.period)
        applied = await self._settle(
            keys=[
                key_spent,
                key_reserved,
                team_spent,
                team_reserved,
                f"resv:{reservation.reservation_id}",
                PENDING_KEY,
            ],
            args=[reservation.estimate_micro, max(0, int(real_micro)), reservation.reservation_id],
        )
        return int(applied) == 1

    async def expire_due(self, now_ms: int, *, limit: int = 100) -> list[dict[str, Any]]:
        """Sweeper: reconcilia reservas cujo TTL passou, cobrando a estimativa (limite superior).

        Cobrar a estimativa é conservador: um pedido que morreu a meio pode já ter consumido
        tokens no provider, e a estimativa é o máximo que podia ter gasto. Devolve os payloads
        das reservas efectivamente reconciliadas, para o registo de uso.
        """
        ids = await self._redis.zrangebyscore(PENDING_KEY, "-inf", now_ms, start=0, num=limit)
        expired: list[dict[str, Any]] = []
        for raw_id in ids:
            reservation_id = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
            raw = await self._redis.get(f"resv:{reservation_id}")
            if raw is None:
                await self._redis.zrem(PENDING_KEY, reservation_id)
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                await self._redis.zrem(PENDING_KEY, reservation_id)
                continue
            if not isinstance(payload, dict) or "estimate_micro" not in payload:
                await self._redis.zrem(PENDING_KEY, reservation_id)
                continue
            reservation = Reservation(
                reservation_id=reservation_id,
                period=str(payload.get("period", "")),
                key_scope=str(payload.get("key_scope", "")),
                team_scope=str(payload.get("team_scope", "")),
                estimate_micro=int(payload["estimate_micro"]),
                payload=payload,
            )
            if await self.settle(reservation, real_micro=reservation.estimate_micro):
                expired.append(payload)
        return expired

    async def rebuild_spent(self, scope_id: str, period: str, spent_micro: int) -> bool:
        """Define o contador `spent` a partir do Postgres, só se ainda não existir (SET NX)."""
        spent_key, _ = _counter_names(scope_id, period)
        return bool(await self._redis.set(spent_key, int(spent_micro), nx=True))

    async def snapshot(self, scope_id: str, period: str) -> dict[str, int]:
        spent_key, reserved_key = _counter_names(scope_id, period)
        spent = await self._redis.get(spent_key)
        reserved = await self._redis.get(reserved_key)
        return {
            "spent_micro": int(spent) if spent is not None else 0,
            "reserved_micro": int(reserved) if reserved is not None else 0,
        }
