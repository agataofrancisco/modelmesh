"""Circuit breaker por (provider, modelo), com estado partilhado em Redis entre réplicas.

Estados: `closed` -> (taxa de falhas na janela) -> `open` -> (cooldown) -> `half_open`
-> (probe com sucesso) -> `closed`, ou (probe com falha) -> `open`.
Ver docs/learn/05-circuit-breaker.md e os testes em tests/unit/test_circuit_breaker.py.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from redis.asyncio import Redis

from gateway.app.clock import Clock
from gateway.app.limits.rate_limiter import load_lua
from gateway.app.providers.base import Hop

LUA_DIR = Path(__file__).resolve().parent / "lua"

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


def _prefix(hop: Hop) -> str:
    return f"cb:{hop.provider}:{hop.model}"


class CircuitBreaker:
    def __init__(
        self,
        redis: Redis,
        clock: Clock,
        *,
        window_s: float,
        min_requests: int,
        failure_ratio: float,
        cooldown_s: float,
        probe_ttl_s: float = 15.0,
    ) -> None:
        self._redis = redis
        self._clock = clock
        self._window_ms = int(window_s * 1000)
        self._min_requests = min_requests
        self._ratio = failure_ratio
        self._cooldown_ms = int(cooldown_s * 1000)
        self._probe_ttl_ms = int(probe_ttl_s * 1000)
        self._check = redis.register_script(load_lua("circuit_check.lua", LUA_DIR))
        self._record_script = redis.register_script(load_lua("circuit_record.lua", LUA_DIR))

    async def allow(self, hop: Hop) -> bool:
        prefix = _prefix(hop)
        result = await self._check(
            keys=[prefix, f"{prefix}:probe"],
            args=[int(self._clock.wall_ms()), self._probe_ttl_ms],
        )
        return int(result) == 1

    async def record(self, hop: Hop, *, ok: bool) -> str:
        prefix = _prefix(hop)
        result = await self._record_script(
            keys=[prefix, f"{prefix}:all", f"{prefix}:fail", f"{prefix}:probe"],
            args=[
                int(self._clock.wall_ms()),
                self._window_ms,
                self._min_requests,
                self._ratio,
                self._cooldown_ms,
                "1" if ok else "0",
                uuid.uuid4().hex,
            ],
        )
        return result.decode() if isinstance(result, bytes) else str(result)

    async def state(self, hop: Hop) -> str:
        raw = await self._redis.hget(_prefix(hop), "state")
        if raw is None:
            return CLOSED
        return raw.decode() if isinstance(raw, bytes) else str(raw)
