"""Fábrica da aplicação FastAPI: composição, middleware, handlers de erro e lifespan."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.trace import Tracer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.app.accounting.prices import PriceBook, PriceEntry
from gateway.app.accounting.redaction import RedactingFilter
from gateway.app.api import admin, admin_ops, health, inference
from gateway.app.budget.ledger import BudgetLedger
from gateway.app.budget.sweeper import sweeper_loop
from gateway.app.clock import Clock
from gateway.app.container import Services
from gateway.app.errors import ERROR_CATALOG, GatewayError, error_body, gateway_error_handler
from gateway.app.limits.rate_limiter import RateLimiter
from gateway.app.observability.metrics import GatewayMetrics
from gateway.app.observability.tracing import build_tracer_provider, get_tracer
from gateway.app.pipeline import ChatPipeline
from gateway.app.policy.circuit import CircuitBreaker
from gateway.app.providers.openai_compatible import OpenAICompatibleAdapter
from gateway.app.settings import Settings, get_settings
from gateway.app.store import repository
from gateway.app.store.db import make_engine, make_session_factory

logger = logging.getLogger("modelmesh")


def _configure_logging(level: str) -> None:
    root = logging.getLogger("modelmesh")
    root.setLevel(level.upper())
    if not any(isinstance(f, RedactingFilter) for f in root.filters):
        root.addFilter(RedactingFilter())
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(handler)


async def _load_prices(services: Services) -> PriceBook:
    book = PriceBook()
    async with services.session_factory() as session:
        for row in await repository.list_prices(session):
            book.add(
                PriceEntry(
                    provider=row.provider,
                    model=row.model,
                    input_per_mtok=row.input_per_mtok,
                    output_per_mtok=row.output_per_mtok,
                    currency=row.currency,
                    effective_date=row.effective_date,
                    source=row.source,
                )
            )
    return book


def create_app(
    settings: Settings | None = None,
    *,
    redis: Redis | None = None,
    engine: AsyncEngine | None = None,
    http_client: httpx.AsyncClient | None = None,
    clock: Clock | None = None,
    prices: PriceBook | None = None,
    span_exporter: SpanExporter | None = None,
    run_sweeper: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging(settings.log_level)
    clock = clock or Clock()
    engine = engine or make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    redis = redis or Redis.from_url(
        settings.redis_url, socket_timeout=2.0, socket_connect_timeout=1.0
    )
    http = http_client or httpx.AsyncClient(
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        timeout=httpx.Timeout(5.0, connect=1.0),
    )
    provider: TracerProvider = build_tracer_provider(
        exporter=span_exporter, otlp_endpoint=settings.otel_exporter_otlp_endpoint
    )
    tracer: Tracer = get_tracer(provider)

    services = Services(
        settings=settings,
        clock=clock,
        engine=engine,
        session_factory=session_factory,
        redis=redis,
        http=http,
        adapter=OpenAICompatibleAdapter(settings.providers, http),
        rate_limiter=RateLimiter(redis, clock, concurrency_ttl_s=settings.concurrency_safety_ttl_s),
        budget=BudgetLedger(redis, reservation_ttl_s=settings.reservation_ttl_s),
        breaker=CircuitBreaker(
            redis,
            clock,
            window_s=settings.circuit_window_s,
            min_requests=settings.circuit_min_requests,
            failure_ratio=settings.circuit_failure_ratio,
            cooldown_s=settings.circuit_cooldown_s,
        ),
        metrics=GatewayMetrics(),
        prices=prices or PriceBook(),
        tracer=tracer,
        tracer_provider=provider,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if prices is None:
            try:
                services.prices = await _load_prices(services)
            except Exception:  # noqa: BLE001 - sem base de dados, os preços ficam vazios (fail-closed)
                logger.exception("não foi possível carregar a tabela de preços")
        task = None
        if run_sweeper:
            task = asyncio.create_task(sweeper_loop(services))
            services.sweeper_task = task
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
            if http_client is None:
                await http.aclose()
            if redis is not None and hasattr(redis, "aclose"):
                await redis.aclose()

    app = FastAPI(
        title="ModelMesh Gateway",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.services = services
    app.state.pipeline = ChatPipeline(services)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = f"req_{uuid.uuid4().hex}"
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)
        response.headers["x-modelmesh-request-id"] = request_id
        logger.info(
            "%s %s %s %dms request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            int((time.monotonic() - started) * 1000),
            request_id,
        )
        return response

    app.add_exception_handler(GatewayError, gateway_error_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        if request.url.path.startswith("/v1/"):
            return JSONResponse(
                error_body("invalid_request", "pedido inválido", request_id),
                status_code=400,
            )
        # Sem valores de entrada na resposta: só localização e mensagem.
        details = [
            {"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            error_body(
                "validation_error",
                "pedido de administração inválido",
                request_id,
                {"errors": details},
            ),
            status_code=ERROR_CATALOG["validation_error"][0],
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.error("erro interno (%s)", type(exc).__name__, extra={"request_id": request_id})
        return JSONResponse(
            error_body("internal_error", "erro interno", request_id), status_code=500
        )

    app.include_router(health.router)
    app.include_router(inference.router)
    app.include_router(admin.router)
    app.include_router(admin_ops.router)
    return app
