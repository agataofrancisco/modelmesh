"""Pipeline de um pedido de inferência:

    policy -> rate limit -> budget reserve -> route (hops) -> reconcile -> record

A autenticação ocorre antes, na dependência FastAPI. Cada etapa é um span OpenTelemetry e cada
decisão fica explicável em cabeçalhos `x-modelmesh-*` e no registo de uso.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from redis.exceptions import RedisError

from gateway.app.accounting.prices import (
    PriceEntry,
    budget_usd_to_micro,
    cost_micro,
    estimate_tokens,
    micro_to_usd,
)
from gateway.app.accounting.redaction import redact
from gateway.app.api.schemas import ChatCompletionRequest, ChatMessage
from gateway.app.auth.dependencies import Principal
from gateway.app.budget.ledger import BudgetExceeded, BudgetScope, Reservation
from gateway.app.container import Services
from gateway.app.errors import GatewayError
from gateway.app.limits.rate_limiter import RateLimitDenied, ScopeLimits
from gateway.app.policy.executor import ClientRouteError, RouteError, RouteExecutor, RouteResult
from gateway.app.policy.resolver import ResolvedRoute, resolve_route
from gateway.app.policy.schemas import HopSpec, TeamPolicy
from gateway.app.providers.base import Hop, ProviderError
from gateway.app.store import repository

logger = logging.getLogger("modelmesh.pipeline")

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_ORPHAN = "orphan_released"


def estimate_input_tokens(messages: list[ChatMessage]) -> int:
    """Estimativa conservadora da entrada: ~4 caracteres/token mais overhead por mensagem."""
    total = 2
    for message in messages:
        content = message.content
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                part["text"]
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        else:
            text = ""
        total += estimate_tokens(text) + 4
    return total


def hops_of(chain: tuple[HopSpec, ...]) -> tuple[Hop, ...]:
    return tuple(Hop(provider=h.provider, model=h.model) for h in chain)


def _price_for_hop(services: Services, hop: Hop, on: datetime) -> PriceEntry:
    price = services.prices.price_for(hop.provider, hop.model, on.date())
    if price is None:
        raise GatewayError(
            "pricing_missing",
            "modelo permitido sem preço configurado para a data do pedido",
            details={"provider": hop.provider, "model": hop.model},
        )
    return price


@dataclass(frozen=True)
class ChatResult:
    body: dict[str, Any]
    headers: dict[str, str]


class ChatPipeline:
    def __init__(self, services: Services) -> None:
        self._s = services
        self._tracer = services.tracer or trace.get_tracer("modelmesh.gateway")
        self._executor = RouteExecutor(
            services.adapter,
            services.breaker,
            services.clock,
            retry_base_s=services.settings.retry_base_s,
            retry_cap_s=services.settings.retry_cap_s,
            rng=services.rng,
            tracer=self._tracer,
        )

    async def _load_policy(self, team_id: str) -> TeamPolicy:
        async with self._s.session_factory() as session:
            row = await repository.latest_policy(session, team_id)
        if row is None:
            raise GatewayError("forbidden", "equipa sem política configurada")
        return TeamPolicy.model_validate(row.body)

    def _redis_unavailable(self, exc: Exception) -> GatewayError:
        logger.error("redis indisponível: %s", type(exc).__name__)
        return GatewayError(
            "service_unavailable",
            "serviço de limites indisponível; pedido recusado (fail-closed)",
        )

    async def handle(
        self,
        request: ChatCompletionRequest,
        principal: Principal,
        *,
        request_id: str,
    ) -> ChatResult:
        clock = self._s.clock
        started_ms = clock.monotonic_ms()
        now = datetime.now(UTC)

        with self._tracer.start_as_current_span("chat.completions") as root:
            root.set_attribute("modelmesh.team", principal.team_id)
            root.set_attribute("modelmesh.request_id", request_id)
            trace_id = format(root.get_span_context().trace_id, "032x")

            with self._tracer.start_as_current_span("policy"):
                policy = await self._load_policy(principal.team_id)
                route = resolve_route(policy, request.model)
                max_tokens = request.max_tokens or route.max_tokens
                if max_tokens > route.max_tokens:
                    raise GatewayError(
                        "max_tokens_exceeded",
                        f"max_tokens acima do permitido pela política ({route.max_tokens})",
                    )
                estimate_in = estimate_input_tokens(request.messages)
                hops = hops_of(route.chain)
                prices = {hop: _price_for_hop(self._s, hop, now) for hop in hops}
                estimate_micro = max(
                    cost_micro(prices[hop], estimate_in, max_tokens) for hop in hops
                )

            ctx = _Context(
                principal=principal,
                policy=policy,
                route=route,
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                estimate_in=estimate_in,
                max_tokens=max_tokens,
                estimate_micro=estimate_micro,
                prices=prices,
                started_ms=started_ms,
            )
            lease = await self._acquire_rate(ctx)
            try:
                reservation = await self._reserve_budget(ctx)
                return await self._execute_and_settle(ctx, reservation)
            finally:
                if lease is not None:
                    await self._release_rate(lease)

    async def _acquire_rate(self, ctx: _Context) -> Any:
        p = ctx.principal
        policy = ctx.policy
        key_scope = ScopeLimits(
            scope_id=f"key:{p.key_id}",
            rpm=p.rpm_limit or 0,
            tpm=p.tpm_limit or 0,
            concurrency=p.concurrency_limit or 0,
        )
        team_scope = ScopeLimits(
            scope_id=f"team:{p.team_id}",
            rpm=policy.rpm,
            tpm=policy.tpm,
            concurrency=policy.concurrency,
        )
        with self._tracer.start_as_current_span("rate_limit"):
            try:
                return await self._s.rate_limiter.acquire(
                    key_scope,
                    team_scope,
                    est_tokens=ctx.estimate_in + ctx.max_tokens,
                    member=ctx.request_id,
                )
            except RateLimitDenied as denied:
                self._s.metrics.rate_limit_rejections.labels(
                    team=p.team_id, scope=denied.scope, kind=denied.kind
                ).inc()
                retry_after = str(max(1, math.ceil(denied.retry_after_ms / 1000)))
                raise GatewayError(
                    "rate_limited",
                    f"limite de {denied.kind} atingido",
                    details={"scope": denied.scope, "kind": denied.kind},
                    headers={"retry-after": retry_after},
                ) from denied
            except RedisError as exc:
                raise self._redis_unavailable(exc) from exc

    async def _release_rate(self, lease: Any) -> None:
        try:
            await self._s.rate_limiter.release(lease)
        except RedisError:
            logger.error("falha a libertar concorrência; o TTL de segurança a corrige")

    async def _reserve_budget(self, ctx: _Context) -> Reservation:
        p = ctx.principal
        budget_key = budget_usd_to_micro(p.budget_usd) if p.budget_usd is not None else -1
        monthly = ctx.policy.budget_usd_monthly
        budget_team = budget_usd_to_micro(monthly) if monthly is not None else -1
        key_scope = BudgetScope(scope_id=f"key:{p.key_id}", budget_micro=budget_key)
        team_scope = BudgetScope(scope_id=f"team:{p.team_id}", budget_micro=budget_team)
        payload = {
            "request_id": ctx.request_id,
            "team_id": p.team_id,
            "key_id": p.key_id,
            "key_prefix": p.key_prefix,
            "model_requested": ctx.request.model,
            "trace_id": ctx.trace_id,
        }
        with self._tracer.start_as_current_span("budget.reserve") as span:
            span.set_attribute("modelmesh.estimate_micro", ctx.estimate_micro)
            try:
                return await self._s.budget.reserve(
                    key_scope,
                    team_scope,
                    estimate_micro=ctx.estimate_micro,
                    now_ms=self._s.clock.wall_ms(),
                    payload=payload,
                )
            except BudgetExceeded as exceeded:
                self._s.metrics.budget_rejections.labels(team=p.team_id, scope=exceeded.scope).inc()
                raise GatewayError(
                    "budget_exceeded",
                    "orçamento insuficiente para este pedido",
                    details={"scope": exceeded.scope},
                ) from exceeded
            except RedisError as exc:
                raise self._redis_unavailable(exc) from exc

    async def _execute_and_settle(self, ctx: _Context, reservation: Reservation) -> ChatResult:
        upstream_body = self._upstream_body(ctx)
        route = ctx.route
        try:
            with self._tracer.start_as_current_span("route") as span:
                span.set_attribute("modelmesh.chain_length", len(route.chain))
                result = await self._executor.run(
                    hops_of(route.chain),
                    upstream_body,
                    max_hops=ctx.policy.max_hops,
                    retries_per_hop=ctx.policy.retries_per_hop,
                    hop_timeout_ms=ctx.policy.hop_timeout_ms,
                    total_timeout_ms=ctx.policy.timeout_ms,
                )
        except (RouteError, ClientRouteError) as error:
            await self._settle(reservation, real_micro=0, ctx=ctx)
            await self._record_failure(ctx, error)
            raise self._map_route_error(ctx, error) from error
        except Exception:
            await self._settle(reservation, real_micro=0, ctx=ctx)
            raise

        return await self._finish_success(ctx, reservation, result)

    def _upstream_body(self, ctx: _Context) -> dict[str, Any]:
        body = ctx.request.model_dump(exclude_none=True, exclude={"model", "stream"})
        body["max_tokens"] = ctx.max_tokens
        return body

    async def _finish_success(
        self, ctx: _Context, reservation: Reservation, result: RouteResult
    ) -> ChatResult:
        served = result.hop
        served_price = ctx.prices.get(served) or _price_for_hop(self._s, served, datetime.now(UTC))
        usage = result.response.usage
        if usage is not None:
            tokens_in, tokens_out = usage.prompt_tokens, usage.completion_tokens
            real_micro = cost_micro(served_price, tokens_in, tokens_out)
            usage_estimated = False
        else:
            # Sem usage: mantém o custo estimado para o hop servido (conservador).
            tokens_in, tokens_out = ctx.estimate_in, ctx.max_tokens
            real_micro = cost_micro(served_price, tokens_in, tokens_out)
            usage_estimated = True

        await self._settle(reservation, real_micro=real_micro, ctx=ctx)
        self._record_success_metrics(ctx, result, tokens_in, tokens_out, real_micro)

        fallback_path = result.fallback_path
        record = self._usage_record(
            ctx,
            status=STATUS_OK,
            served=served,
            fallback_path=fallback_path,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            real_micro=real_micro,
            estimate_micro=reservation.estimate_micro,
            usage_estimated=usage_estimated,
        )
        await self._persist(record)

        body = dict(result.response.body)
        body["model"] = served.model
        headers = {
            "x-modelmesh-request-id": ctx.request_id,
            "x-modelmesh-trace-id": ctx.trace_id,
            "x-modelmesh-requested-model": ctx.request.model,
            "x-modelmesh-model": ctx.route.served_model,
            "x-modelmesh-provider": served.provider,
            "x-modelmesh-fallback-path": "->".join(fallback_path),
            "x-modelmesh-usage-estimated": "true" if usage_estimated else "false",
        }
        return ChatResult(body=body, headers=headers)

    async def _settle(self, reservation: Reservation, *, real_micro: int, ctx: _Context) -> None:
        with self._tracer.start_as_current_span("budget.reconcile"):
            try:
                await self._s.budget.settle(reservation, real_micro=real_micro)
            except RedisError:
                # O sweeper reconcilia pela estimativa após o TTL: o orçamento continua seguro.
                logger.error("reconciliação adiada para o sweeper (request %s)", ctx.request_id)

    def _record_success_metrics(
        self, ctx: _Context, result: RouteResult, tokens_in: int, tokens_out: int, real_micro: int
    ) -> None:
        m = self._s.metrics
        team = ctx.principal.team_id
        served = result.hop
        path = result.fallback_path
        for failed, nxt in zip(path, path[1:], strict=False):
            m.fallback.labels(team=team, **{"from": failed, "to": nxt}).inc()
        for attempt in result.attempts:
            m.provider_attempts.labels(provider=attempt.provider, outcome=attempt.outcome).inc()
        m.token_usage.labels(
            team=team, provider=served.provider, model=served.model, direction="input"
        ).inc(tokens_in)
        m.token_usage.labels(
            team=team, provider=served.provider, model=served.model, direction="output"
        ).inc(tokens_out)
        m.estimated_spend.labels(team=team, provider=served.provider, model=served.model).inc(
            float(micro_to_usd(real_micro))
        )
        m.requests.labels(team=team, model=ctx.request.model, status=STATUS_OK).inc()
        elapsed = (self._s.clock.monotonic_ms() - ctx.started_ms) / 1000.0
        m.latency.labels(team=team, model=ctx.request.model).observe(max(0.0, elapsed))

    def _map_route_error(self, ctx: _Context, error: RouteError) -> GatewayError:
        team = ctx.principal.team_id
        hops = [
            {"provider": a.provider, "model": a.model, "outcome": a.outcome} for a in error.attempts
        ]
        if isinstance(error, ClientRouteError):
            provider_error: ProviderError = error.error
            self._s.metrics.errors_by_reason.labels(team=team, reason="upstream_client_error").inc()
            self._s.metrics.requests.labels(
                team=team, model=ctx.request.model, status=STATUS_ERROR
            ).inc()
            return GatewayError(
                "upstream_client_error",
                "o provider recusou o pedido",
                details={"upstream_status": provider_error.status, "attempted_hops": hops},
            )
        if error.timed_out:
            code, message = "timeout", "tempo limite do pedido excedido"
        else:
            code, message = "upstream_unavailable", "todos os providers da cadeia falharam"
        self._s.metrics.errors_by_reason.labels(team=team, reason=code).inc()
        self._s.metrics.requests.labels(
            team=team, model=ctx.request.model, status=STATUS_ERROR
        ).inc()
        return GatewayError(code, message, details={"attempted_hops": hops})

    async def _record_failure(self, ctx: _Context, error: RouteError) -> None:
        path = [a.provider for a in error.attempts if a.outcome != "circuit_open"]
        code = (
            "upstream_client_error"
            if isinstance(error, ClientRouteError)
            else ("timeout" if error.timed_out else "upstream_unavailable")
        )
        record = self._usage_record(
            ctx,
            status=STATUS_ERROR,
            served=None,
            fallback_path=path,
            tokens_in=0,
            tokens_out=0,
            real_micro=0,
            estimate_micro=ctx.estimate_micro,
            usage_estimated=False,
            error_code=code,
        )
        await self._persist(record)

    def _usage_record(
        self,
        ctx: _Context,
        *,
        status: str,
        served: Hop | None,
        fallback_path: list[str],
        tokens_in: int,
        tokens_out: int,
        real_micro: int,
        estimate_micro: int,
        usage_estimated: bool,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        p = ctx.principal
        return {
            "request_id": ctx.request_id,
            "team_id": p.team_id,
            "key_id": p.key_id,
            "key_prefix": p.key_prefix,
            "model_requested": ctx.request.model,
            "model_served": served.model if served else None,
            "provider_served": served.provider if served else None,
            "fallback_path": fallback_path,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_estimated_usd": micro_to_usd(estimate_micro),
            "cost_real_usd": micro_to_usd(real_micro),
            "usage_estimated": usage_estimated,
            "latency_ms": int(self._s.clock.monotonic_ms() - ctx.started_ms),
            "status": status,
            "error_code": error_code,
            "trace_id": ctx.trace_id,
        }

    async def _persist(self, record: dict[str, Any]) -> None:
        try:
            async with self._s.session_factory() as session:
                await repository.insert_usage(session, record)
        except Exception as exc:  # noqa: BLE001 - o pedido já foi servido; regista e segue
            logger.error("falha a gravar registo de uso: %s", redact(str(exc)))


@dataclass
class _Context:
    principal: Principal
    policy: TeamPolicy
    route: ResolvedRoute
    request: ChatCompletionRequest
    request_id: str
    trace_id: str
    estimate_in: int
    max_tokens: int
    estimate_micro: int
    prices: dict[Hop, PriceEntry]
    started_ms: float
