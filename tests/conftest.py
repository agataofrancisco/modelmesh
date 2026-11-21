"""Fixtures partilhadas: gateway em processo, Redis falso (fakeredis) e mocks por ASGI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fakeredis
import httpx
import pytest

from gateway.app.accounting.prices import PriceBook
from gateway.app.clock import FakeClock
from gateway.app.main import create_app
from gateway.app.providers.mock_server import MockProfile, create_mock_app
from gateway.app.store.db import make_engine, make_session_factory
from tests.support import (
    MOCK_A_PORT,
    MOCK_B_PORT,
    PortRoutingTransport,
    create_schema,
    fixed_prices,
    make_settings,
)


@dataclass
class Env:
    app: Any
    client: httpx.AsyncClient
    services: Any
    session_factory: Any
    redis: Any
    mock_a: Any
    mock_b: Any
    clock: FakeClock
    http: httpx.AsyncClient
    engine: Any = None


async def build_env(tmp_path: Path, *, redis=None, clock=None, prices=None, **settings_over):  # noqa: ANN001, ANN201
    redis = redis or fakeredis.FakeAsyncRedis()
    clock = clock or FakeClock()
    settings = make_settings(tmp_path, **settings_over)
    engine = make_engine(settings.database_url)
    await create_schema(engine)
    session_factory = make_session_factory(engine)
    mock_a_app = create_mock_app("mock_a", MockProfile(seed=7))
    mock_b_app = create_mock_app("mock_b", MockProfile(seed=11))
    http = httpx.AsyncClient(
        transport=PortRoutingTransport(
            {
                MOCK_A_PORT: httpx.ASGITransport(app=mock_a_app),
                MOCK_B_PORT: httpx.ASGITransport(app=mock_b_app),
            }
        )
    )
    app = create_app(
        settings,
        redis=redis,
        engine=engine,
        http_client=http,
        clock=clock,
        prices=PriceBook(fixed_prices()) if prices is None else prices,
        run_sweeper=False,
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw")
    return Env(
        app=app,
        client=client,
        services=app.state.services,
        session_factory=session_factory,
        redis=redis,
        mock_a=mock_a_app.state.mock,
        mock_b=mock_b_app.state.mock,
        clock=clock,
        http=http,
        engine=engine,
    )


@pytest.fixture
async def env(tmp_path: Path):  # noqa: ANN201
    environment = await build_env(tmp_path)
    yield environment
    await environment.client.aclose()
    await environment.http.aclose()
    await environment.redis.aclose()
    await environment.engine.dispose()
