"""Rate limit atómico (RPM por janela deslizante, TPM estimado por minuto, concorrência).

A verificação e o incremento acontecem num único script Lua (`lua/acquire.lua`), portanto
duas réplicas nunca vêem o mesmo "espaço livre". Ver docs/learn/06-rate-limiting-redis-lua.md.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from redis.asyncio import Redis

from gateway.app.clock import Clock

WINDOW_MS = 60_000
_REASONS = {
    1: ("key", "rpm"),
    2: ("key", "tpm"),
    3: ("key", "concurrency"),
    4: ("team", "rpm"),
    5: ("team", "tpm"),
    6: ("team", "concurrency"),
}


LUA_DIR = Path(__file__).resolve().parent / "lua"


def load_lua(name: str, directory: Path = LUA_DIR) -> str:
    return (directory / name).read_text(encoding="utf-8")


@dataclass(frozen=True)
class ScopeLimits:
    """Limites de um âmbito. 0 significa sem limite."""

    scope_id: str  # ex.: "key:ab12" ou "team:suporte"
    rpm: int = 0
    tpm: int = 0
    concurrency: int = 0


class RateLimitDenied(Exception):
    def __init__(self, scope: str, kind: str, retry_after_ms: int) -> None:
        self.scope = scope
        self.kind = kind
        self.retry_after_ms = max(1, int(retry_after_ms))
        super().__init__(f"rate limit {kind} ({scope})")


@dataclass
class Lease:
    """Resultado de um acquire bem-sucedido. `release` tem de ser chamado sempre (finally)."""

    concurrency_keys: list[str]
    member: str
    released: bool = False


class RateLimiter:
    def __init__(self, redis: Redis, clock: Clock, *, concurrency_ttl_s: int) -> None:
        self._redis = redis
        self._clock = clock
        self._concurrency_ttl_ms = concurrency_ttl_s * 1000
        self._acquire = redis.register_script(load_lua("acquire.lua"))
        self._release = redis.register_script(load_lua("release.lua"))

    @staticmethod
    def _keys(scope: ScopeLimits, minute: int) -> list[str]:
        base = f"rl:{scope.scope_id}"
        return [f"{base}:rpm", f"{base}:tpm:{minute}", f"{base}:conc:v2"]

    async def acquire(
        self,
        key_scope: ScopeLimits,
        team_scope: ScopeLimits,
        *,
        est_tokens: int,
        member: str | None = None,
    ) -> Lease:
        now = self._clock.wall_ms()
        minute = now // WINDOW_MS
        keys = self._keys(key_scope, minute) + self._keys(team_scope, minute)
        request_member = uuid.uuid4().hex
        lease_member = uuid.uuid4().hex
        args = [
            now,
            WINDOW_MS,
            WINDOW_MS * 2,
            max(0, int(est_tokens)),
            member or request_member,
            self._concurrency_ttl_ms,
            key_scope.rpm,
            key_scope.tpm,
            key_scope.concurrency,
            team_scope.rpm,
            team_scope.tpm,
            team_scope.concurrency,
            lease_member,
        ]
        result: list[Any] = await self._acquire(keys=keys, args=args)
        allowed, reason, retry = int(result[0]), int(result[1]), int(result[2])
        if allowed:
            conc_keys = [
                self._keys(scope, minute)[2]
                for scope in (key_scope, team_scope)
                if scope.concurrency > 0
            ]
            return Lease(concurrency_keys=conc_keys, member=lease_member)
        scope_name, kind = _REASONS[reason]
        raise RateLimitDenied(scope_name, kind, retry)

    async def release(self, lease: Lease) -> None:
        if lease.released or not lease.concurrency_keys:
            lease.released = True
            return
        lease.released = True
        await self._release(keys=lease.concurrency_keys, args=[lease.member])
