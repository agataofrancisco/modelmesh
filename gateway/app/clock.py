"""Relógio injetável. Em produção usa o relógio real; nos testes, `FakeClock` avança o tempo
sem esperar, o que permite testar backoff, deadlines e cooldowns de forma determinística."""

from __future__ import annotations

import asyncio
import time


class Clock:
    """Relógio real: tempo monotónico em milissegundos e sleep assíncrono."""

    def monotonic_ms(self) -> float:
        return time.monotonic() * 1000.0

    def wall_ms(self) -> int:
        return int(time.time() * 1000)

    async def sleep(self, seconds: float) -> None:
        if seconds > 0:
            await asyncio.sleep(seconds)


class FakeClock(Clock):
    """Relógio de teste: `sleep` apenas avança o tempo interno."""

    def __init__(self, start_ms: float = 1_000_000.0) -> None:
        self._now_ms = float(start_ms)

    def monotonic_ms(self) -> float:
        return self._now_ms

    def wall_ms(self) -> int:
        return int(self._now_ms)

    def advance_ms(self, ms: float) -> None:
        self._now_ms += ms

    async def sleep(self, seconds: float) -> None:
        self._now_ms += seconds * 1000.0
        await asyncio.sleep(0)
