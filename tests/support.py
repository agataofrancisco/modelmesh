"""Utilitários de teste: transporte que encaminha para mocks em processo, relógio e setup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.app.auth.keys import generate_key
from gateway.app.clock import FakeClock
from gateway.app.settings import ProviderConfig, Settings
from gateway.app.store import repository
from gateway.app.store.models import Base

ADMIN_TOKEN = "test-admin-token-0123456789abcdef"
MOCK_A_PORT = 9001
MOCK_B_PORT = 9002


class PortRoutingTransport(httpx.AsyncBaseTransport):
    """Encaminha cada pedido para o transporte (ASGI) registado para a porta do URL."""

    def __init__(self, routes: dict[int, httpx.AsyncBaseTransport]) -> None:
        self._routes = routes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        port = request.url.port
        transport = self._routes.get(port)
        if transport is None:
            raise httpx.ConnectError(f"sem rota de teste para a porta {port}", request=request)
        return await transport.handle_async_request(request)


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        "redis_url": "redis://127.0.0.1:6399/0",
        "admin_token": ADMIN_TOKEN,
        "providers": {
            "mock_a": ProviderConfig(
                base_url=f"http://127.0.0.1:{MOCK_A_PORT}/v1",
                control_url=f"http://127.0.0.1:{MOCK_A_PORT}",
            ),
            "mock_b": ProviderConfig(
                base_url=f"http://127.0.0.1:{MOCK_B_PORT}/v1",
                control_url=f"http://127.0.0.1:{MOCK_B_PORT}",
            ),
        },
        "retry_base_s": 0.01,
        "retry_cap_s": 0.05,
        "circuit_min_requests": 3,
        "circuit_failure_ratio": 0.5,
        "circuit_window_s": 30.0,
        "circuit_cooldown_s": 5.0,
    }
    values.update(overrides)
    return Settings(**values)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def seed_team_with_policy(session_factory, team_id: str, policy: dict[str, Any]) -> None:  # noqa: ANN001
    async with session_factory() as session:
        await repository.create_team(session, team_id, f"Equipa {team_id}")
        await repository.append_policy(session, team_id, policy)


async def issue_key(session_factory, team_id: str, **limits: Any) -> tuple[str, str]:  # noqa: ANN001
    """Devolve (chave em claro, id da chave). A chave em claro só existe neste teste."""
    issued = generate_key()
    async with session_factory() as session:
        row = await repository.create_key(session, team_id, "teste", issued, **limits)
        return issued.plaintext, row.id


def default_policy(**overrides: Any) -> dict[str, Any]:
    policy: dict[str, Any] = {
        "models": {
            "mock-small": {
                "chain": [
                    {"provider": "mock_a", "model": "mock-small"},
                    {"provider": "mock_b", "model": "mock-small"},
                ]
            },
            "mock-large": {"chain": [{"provider": "mock_b", "model": "mock-large"}]},
        },
        "classes": {"cheap": "mock-small", "critical": "mock-large"},
        "max_tokens": 512,
        "max_hops": 2,
        "retries_per_hop": 1,
        "timeout_ms": 5000,
        "hop_timeout_ms": 1000,
    }
    policy.update(overrides)
    return policy


def fixed_prices() -> list[Any]:
    """Preços de teste (fixos): permitem cálculos exactos nas asserções."""
    from datetime import date
    from decimal import Decimal

    from gateway.app.accounting.prices import PriceEntry

    rows = []
    for provider in ("mock_a", "mock_b"):
        for model in ("mock-small", "mock-large"):
            rows.append(
                PriceEntry(
                    provider=provider,
                    model=model,
                    input_per_mtok=Decimal("1.00"),
                    output_per_mtok=Decimal("2.00"),
                    currency="USD",
                    effective_date=date(2026, 1, 1),
                    source="teste",
                )
            )
    return rows


__all__ = [
    "ADMIN_TOKEN",
    "MOCK_A_PORT",
    "MOCK_B_PORT",
    "FakeClock",
    "PortRoutingTransport",
    "create_schema",
    "default_policy",
    "issue_key",
    "make_settings",
    "seed_team_with_policy",
    "fixed_prices",
]
