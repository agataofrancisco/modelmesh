"""Backoff exponencial com jitter, Retry-After e deadline total.

delay(n) = min(cap, base * 2^n) * U(0.5, 1.5)   (jitter "equal" relativo ao exponencial)
Se o provider devolver Retry-After, o atraso é pelo menos esse valor.
Se o atraso não couber no deadline total, não se espera: o engine passa ao hop seguinte.
"""

from __future__ import annotations

import random

from gateway.app.clock import Clock


def backoff_delay_s(
    attempt: int,
    *,
    base_s: float,
    cap_s: float,
    rng: random.Random,
    retry_after_s: float | None = None,
) -> float:
    """`attempt` começa em 0 para a primeira repetição."""
    if attempt < 0:
        raise ValueError("attempt não pode ser negativo")
    exponential = min(cap_s, base_s * (2 ** min(attempt, 30)))
    jittered = exponential * rng.uniform(0.5, 1.5)
    if retry_after_s is not None:
        jittered = max(jittered, retry_after_s)
    return max(0.0, jittered)


class Deadline:
    """Deadline total de um pedido, medido com o relógio injetado (testável)."""

    def __init__(self, clock: Clock, total_ms: int) -> None:
        self._clock = clock
        self._end_ms = clock.monotonic_ms() + total_ms

    def remaining_ms(self) -> float:
        return max(0.0, self._end_ms - self._clock.monotonic_ms())

    def remaining_s(self) -> float:
        return self.remaining_ms() / 1000.0

    def expired(self) -> bool:
        return self.remaining_ms() <= 0
