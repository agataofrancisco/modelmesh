"""Composição das dependências do gateway (uma instância por aplicação FastAPI)."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field

import httpx
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Tracer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from gateway.app.accounting.prices import PriceBook
from gateway.app.budget.ledger import BudgetLedger
from gateway.app.clock import Clock
from gateway.app.limits.rate_limiter import RateLimiter
from gateway.app.observability.metrics import GatewayMetrics
from gateway.app.policy.circuit import CircuitBreaker
from gateway.app.providers.openai_compatible import OpenAICompatibleAdapter
from gateway.app.settings import Settings


@dataclass
class Services:
    settings: Settings
    clock: Clock
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis
    http: httpx.AsyncClient
    adapter: OpenAICompatibleAdapter
    rate_limiter: RateLimiter
    budget: BudgetLedger
    breaker: CircuitBreaker
    metrics: GatewayMetrics
    prices: PriceBook
    rng: random.Random = field(default_factory=random.Random)
    tracer: Tracer | None = None
    tracer_provider: TracerProvider | None = None
    sweeper_task: asyncio.Task | None = None
