"""Seed demo idempotente: equipas da Órbita Tech, políticas e preços fictícios.

Não cria chaves de API: as chaves são emitidas pela administração e mostradas uma única vez.
Executar: `python -m gateway.app.store.seed` (com MODELMESH_DATABASE_URL definido).
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gateway.app.accounting.prices import SUPPORTED_CURRENCY, parse_price_row
from gateway.app.policy.schemas import TeamPolicy
from gateway.app.store import repository

DEMO_TEAMS: dict[str, str] = {
    "suporte": "Órbita Tech - Suporte",
    "marketing": "Órbita Tech - Marketing",
    "dados": "Órbita Tech - Dados",
}

MOCK_CHAINS: dict[str, dict[str, Any]] = {
    "mock-small": {
        "chain": [
            {"provider": "mock_a", "model": "mock-small"},
            {"provider": "mock_b", "model": "mock-small"},
        ]
    },
    "mock-large": {
        "chain": [
            {"provider": "mock_b", "model": "mock-large"},
            {"provider": "mock_a", "model": "mock-large"},
        ]
    },
}

TEAM_BUDGETS: dict[str, str] = {"suporte": "50", "marketing": "20", "dados": "100"}


def demo_policy(team: str) -> TeamPolicy:
    return TeamPolicy.model_validate(
        {
            "models": MOCK_CHAINS,
            "classes": {"cheap": "mock-small", "balanced": "mock-small", "critical": "mock-large"},
            "max_tokens": 1024,
            "max_hops": 2,
            "retries_per_hop": 1,
            "timeout_ms": 8000,
            "hop_timeout_ms": 3000,
            "rpm": 600,
            "tpm": 500_000,
            "concurrency": 20,
            "budget_usd_monthly": TEAM_BUDGETS[team],
        }
    )


def load_price_rows(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = data.get("prices")
    if not isinstance(rows, list):
        raise ValueError("ficheiro de preços sem lista 'prices'")
    return rows


async def seed_demo(
    session_factory: async_sessionmaker[AsyncSession], prices_path: Path
) -> dict[str, int]:
    created_teams = 0
    created_policies = 0
    async with session_factory() as session:
        for team_id, name in DEMO_TEAMS.items():
            if await repository.get_team(session, team_id) is None:
                await repository.create_team(session, team_id, name)
                created_teams += 1
            if await repository.latest_policy(session, team_id) is None:
                await repository.append_policy(
                    session, team_id, demo_policy(team_id).model_dump(mode="json")
                )
                created_policies += 1

        prices = 0
        for raw in load_price_rows(prices_path):
            entry = parse_price_row(raw)
            await repository.upsert_price(
                session,
                provider=entry.provider,
                model=entry.model,
                input_per_mtok=Decimal(entry.input_per_mtok),
                output_per_mtok=Decimal(entry.output_per_mtok),
                currency=entry.currency or SUPPORTED_CURRENCY,
                effective_date=entry.effective_date
                if isinstance(entry.effective_date, date)
                else date.fromisoformat(str(entry.effective_date)),
                source=entry.source,
            )
            prices += 1
    return {"teams": created_teams, "policies": created_policies, "prices": prices}


def _main() -> None:  # pragma: no cover - CLI
    import os

    from gateway.app.store.db import make_engine, make_session_factory

    url = os.environ.get("MODELMESH_DATABASE_URL", "sqlite+aiosqlite:///./.runtime/modelmesh.db")
    engine = make_engine(url)
    factory = make_session_factory(engine)
    path = Path(os.environ.get("MODELMESH_PRICES_SEED_PATH", "migrations/seed/prices.yaml"))
    result = asyncio.run(seed_demo(factory, path))
    print(result)
    asyncio.run(engine.dispose())


if __name__ == "__main__":  # pragma: no cover
    _main()
