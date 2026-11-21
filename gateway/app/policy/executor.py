"""Motor de execução da cadeia de fallback: circuito, retries, timeouts e deadline total.

Algoritmo, por hop da cadeia (até `max_hops`):
1. Se o circuito do hop estiver aberto, salta-o (não entra no caminho de fallback).
2. Tenta o pedido com timeout = min(timeout do hop, tempo restante do deadline).
3. Sucesso -> devolve. Erro de cliente (4xx exceto 408/429) -> devolve o erro, sem fallback.
4. Erro transitório/timeout -> repete no mesmo hop com backoff+jitter (respeita Retry-After e
   o deadline), até `retries_per_hop`.
5. Erro elegível para fallback (ou retries esgotados) -> passa ao hop seguinte.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from opentelemetry.trace import Tracer

from gateway.app.clock import Clock
from gateway.app.policy.backoff import Deadline, backoff_delay_s
from gateway.app.policy.circuit import CircuitBreaker
from gateway.app.providers.base import (
    CIRCUIT_FAILURE_KINDS,
    KIND_CLIENT,
    Hop,
    ProviderAdapter,
    ProviderError,
    ProviderResponse,
)

OUTCOME_OK = "ok"
OUTCOME_CIRCUIT_OPEN = "circuit_open"
OUTCOME_DEADLINE = "deadline"


@dataclass
class Attempt:
    provider: str
    model: str
    outcome: str  # ok | circuit_open | deadline | kind do ProviderError
    tries: int = 0


@dataclass
class RouteResult:
    response: ProviderResponse
    hop: Hop
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def fallback_path(self) -> list[str]:
        """Providers efectivamente chamados, por ordem, incluindo o que serviu."""
        return [a.provider for a in self.attempts if a.outcome != OUTCOME_CIRCUIT_OPEN]


class RouteError(Exception):
    """Nenhum hop serviu o pedido. `timed_out` indica que o deadline total foi a causa."""

    def __init__(self, attempts: list[Attempt], *, timed_out: bool) -> None:
        self.attempts = attempts
        self.timed_out = timed_out
        super().__init__("todos os hops falharam" if not timed_out else "deadline total excedido")


class ClientRouteError(RouteError):
    """Erro de cliente do provider: não há fallback."""

    def __init__(self, attempts: list[Attempt], error: ProviderError) -> None:
        self.error = error
        super().__init__(attempts, timed_out=False)


class RouteExecutor:
    def __init__(
        self,
        adapter: ProviderAdapter,
        breaker: CircuitBreaker,
        clock: Clock,
        *,
        retry_base_s: float,
        retry_cap_s: float,
        rng: random.Random | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._adapter = adapter
        self._breaker = breaker
        self._clock = clock
        self._retry_base_s = retry_base_s
        self._retry_cap_s = retry_cap_s
        self._rng = rng or random.Random()
        self._tracer = tracer

    async def _call(self, hop: Hop, body: dict, timeout_s: float) -> ProviderResponse:
        if self._tracer is None:
            return await self._adapter.chat(hop, body, timeout_s=timeout_s)
        with self._tracer.start_as_current_span("provider.attempt") as span:
            span.set_attribute("modelmesh.provider", hop.provider)
            span.set_attribute("modelmesh.model", hop.model)
            try:
                return await self._adapter.chat(hop, body, timeout_s=timeout_s)
            except ProviderError as error:
                span.set_attribute("modelmesh.outcome", error.kind)
                raise

    async def run(
        self,
        chain: tuple[Hop, ...] | list[Hop],
        body: dict,
        *,
        max_hops: int,
        retries_per_hop: int,
        hop_timeout_ms: int,
        total_timeout_ms: int,
    ) -> RouteResult:
        deadline = Deadline(self._clock, total_timeout_ms)
        attempts: list[Attempt] = []

        for hop in list(chain)[:max_hops]:
            if deadline.expired():
                attempts.append(Attempt(hop.provider, hop.model, OUTCOME_DEADLINE))
                break
            if not await self._breaker.allow(hop):
                attempts.append(Attempt(hop.provider, hop.model, OUTCOME_CIRCUIT_OPEN))
                continue

            attempt_record = Attempt(hop.provider, hop.model, OUTCOME_DEADLINE)
            attempts.append(attempt_record)
            retry_index = 0
            while True:
                if deadline.expired():
                    attempt_record.outcome = OUTCOME_DEADLINE
                    break
                attempt_record.tries += 1
                timeout_ms = min(float(hop_timeout_ms), deadline.remaining_ms())
                try:
                    response = await self._call(hop, body, max(0.001, timeout_ms / 1000.0))
                except ProviderError as error:
                    if error.kind in CIRCUIT_FAILURE_KINDS:
                        state = await self._breaker.record(hop, ok=False)
                    else:
                        state = None
                    attempt_record.outcome = error.kind
                    if error.kind == KIND_CLIENT:
                        raise ClientRouteError(attempts, error) from error
                    if not error.retryable or retry_index >= retries_per_hop:
                        break
                    if state == "open":
                        break
                    delay = backoff_delay_s(
                        retry_index,
                        base_s=self._retry_base_s,
                        cap_s=self._retry_cap_s,
                        rng=self._rng,
                        retry_after_s=error.retry_after_s,
                    )
                    if delay >= deadline.remaining_s():
                        # Esperar excederia o deadline total: passa ao hop seguinte.
                        break
                    retry_index += 1
                    await self._clock.sleep(delay)
                    continue

                await self._breaker.record(hop, ok=True)
                attempt_record.outcome = OUTCOME_OK
                return RouteResult(response=response, hop=hop, attempts=attempts)

        timed_out = deadline.expired() or (
            bool(attempts) and attempts[-1].outcome == OUTCOME_DEADLINE
        )
        raise RouteError(attempts, timed_out=timed_out)
