"""PostgreSQL real (pgserver, sem Docker): migrações Alembic, seed idempotente e um pedido completo.

Marcador `postgres`: arranca um servidor PostgreSQL local com pgserver na primeira utilização.
"""

import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from gateway.app.accounting.prices import PriceBook
from gateway.app.main import create_app
from gateway.app.settings import Settings
from gateway.app.store.db import make_engine, make_session_factory
from gateway.app.store.models import Team
from gateway.app.store.seed import seed_demo
from tests.support import ADMIN_TOKEN, MOCK_A_PORT, default_policy

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def pg_url():
    pgserver = pytest.importorskip("pgserver")
    server = pgserver.get_server(str(ROOT / ".pgdata"), cleanup_mode="stop")
    uri = server.get_uri()  # postgresql://postgres:@host:port/postgres
    async_url = uri.replace("postgresql://", "postgresql+psycopg://", 1)
    env = {**os.environ, "MODELMESH_DATABASE_URL": async_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    return async_url


async def test_migrations_and_seed_on_postgres(pg_url):
    engine = make_engine(pg_url)
    factory = make_session_factory(engine)
    try:
        first = await seed_demo(factory, ROOT / "migrations" / "seed" / "prices.yaml")
        second = await seed_demo(factory, ROOT / "migrations" / "seed" / "prices.yaml")
        assert first["prices"] == 4  # quatro linhas de preço no seed
        assert second["teams"] == 0 and second["policies"] == 0
        async with factory() as session:
            count = (await session.execute(select(func.count()).select_from(Team))).scalar_one()
            assert count >= 3
    finally:
        await engine.dispose()


async def test_full_request_on_postgres_backend(pg_url, tmp_path):
    """Pedido completo: chave em Postgres, política em Postgres, registo de uso em Postgres."""
    from sqlalchemy import select as sel

    from gateway.app.store.models import UsageRecord
    from tests.support import MOCK_B_PORT, PortRoutingTransport

    engine = make_engine(pg_url)
    factory = make_session_factory(engine)
    await seed_demo(factory, ROOT / "migrations" / "seed" / "prices.yaml")
    settings = Settings(
        database_url=pg_url,
        redis_url="redis://127.0.0.1:1/0",
        admin_token=ADMIN_TOKEN,
    )
    import fakeredis

    from gateway.app.providers.mock_server import MockProfile, create_mock_app

    mock_a = create_mock_app("mock_a", MockProfile(seed=1))
    mock_b = create_mock_app("mock_b", MockProfile(seed=2))
    http = httpx.AsyncClient(
        transport=PortRoutingTransport(
            {
                MOCK_A_PORT: httpx.ASGITransport(app=mock_a),
                MOCK_B_PORT: httpx.ASGITransport(app=mock_b),
            }
        )
    )
    redis = fakeredis.FakeAsyncRedis()
    from gateway.app.accounting.prices import (
        PriceEntry,  # noqa: F401
        parse_price_row,
    )
    from gateway.app.store.seed import load_price_rows

    book = PriceBook(
        parse_price_row(r) for r in load_price_rows(ROOT / "migrations" / "seed" / "prices.yaml")
    )
    app = create_app(
        settings, redis=redis, engine=engine, http_client=http, prices=book, run_sweeper=False
    )
    client = (
        httpx.AsyncClient(transport=httpx.ASGITorTransport(app=app))
        if False
        else httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw")
    )
    admin = {"authorization": f"Bearer {ADMIN_TOKEN}"}
    try:
        team = f"pg{os.getpid()}"
        await client.post("/admin/teams", json={"id": team, "name": "PG"}, headers=admin)
        await client.put(f"/admin/policies/{team}", json=default_policy(), headers=admin)
        key = (
            await client.post("/admin/keys", json={"team_id": team, "name": "pg"}, headers=admin)
        ).json()["key"]
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "mock-small", "messages": [{"role": "user", "content": "olá"}]},
            headers={"authorization": f"Bearer {key}"},
        )
        assert response.status_code == 200, response.text
        async with factory() as session:
            row = (
                await session.execute(sel(UsageRecord).where(UsageRecord.team_id == team))
            ).scalar_one()
            assert row.status == "ok" and row.cost_real_usd > 0
    finally:
        await client.aclose()
        await http.aclose()
        await redis.aclose()
        await engine.dispose()
