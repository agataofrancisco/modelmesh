"""Servidores HTTP reais (uvicorn em threads) para testes com o SDK síncrono da OpenAI.

As factories são importadas pelo uvicorn dentro da thread do servidor, para que cada app
crie as suas ligações no loop correcto. A configuração chega por variáveis de ambiente.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

import fakeredis
import uvicorn

from gateway.app.providers.mock_server import MockProfile, create_mock_app
from gateway.app.settings import ProviderConfig, Settings


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def build_mock_a():  # noqa: ANN201 - factory do uvicorn
    return create_mock_app("mock_a", MockProfile(**json.loads(os.environ.get("MM_MOCK_A", "{}"))))


def build_mock_b():  # noqa: ANN201
    return create_mock_app("mock_b", MockProfile(**json.loads(os.environ.get("MM_MOCK_B", "{}"))))


def build_gateway():  # noqa: ANN201

    settings = Settings(
        database_url=os.environ["MM_DB_URL"],
        redis_url="redis://127.0.0.1:1/0",
        admin_token=os.environ["MM_ADMIN_TOKEN"],
        providers={
            "mock_a": ProviderConfig(
                base_url=os.environ["MM_MOCK_A_URL"], control_url=os.environ["MM_MOCK_A_CTRL"]
            ),
            "mock_b": ProviderConfig(
                base_url=os.environ["MM_MOCK_B_URL"], control_url=os.environ["MM_MOCK_B_CTRL"]
            ),
        },
        retry_base_s=0.01,
        retry_cap_s=0.05,
    )
    redis = fakeredis.FakeAsyncRedis()
    return create_mock_gateway(settings, redis)


def create_mock_gateway(settings: Settings, redis):  # noqa: ANN001, ANN201
    from gateway.app.accounting.prices import PriceBook
    from gateway.app.main import create_app
    from gateway.app.store.db import make_engine
    from tests.support import fixed_prices

    engine = make_engine(settings.database_url)
    # Lifespan não corre nestes servidores: os preços de teste são passados explicitamente.
    return create_app(
        settings, redis=redis, engine=engine, run_sweeper=False, prices=PriceBook(fixed_prices())
    )


def create_schema_sync(database_url: str) -> None:
    """Schema criado de forma síncrona antes de arrancar os servidores (fora do loop do uvicorn)."""
    from sqlalchemy import create_engine

    from gateway.app.store.models import Base

    sync_url = database_url.replace("+aiosqlite", "")
    engine = create_engine(sync_url)
    Base.metadata.create_all(engine)
    engine.dispose()


class ThreadServer:
    def __init__(self, factory: str, port: int) -> None:
        self.port = port
        config = uvicorn.Config(
            factory, factory=True, host="127.0.0.1", port=port, log_level="warning", lifespan="off"
        )
        self.server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        deadline = time.time() + 15
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError(f"servidor na porta {self.port} não arrancou")
            time.sleep(0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        self._thread.join(timeout=10)


def sqlite_url(directory: Path) -> str:
    return f"sqlite+aiosqlite:///{(directory / 'live.db').as_posix()}"
