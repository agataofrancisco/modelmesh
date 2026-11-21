"""Concorrência com sockets reais contra um servidor fakeredis TCP.

ATENÇÃO: isto é o `fakeredis.TcpFakeServer` (protocolo Redis em socket, implementação Python),
NÃO é Redis real. Serve para provar que as ligações concorrentes via redis-py não furam o limite
do script Lua. A prova com Redis real está em test_redis_real.py (marcador `redis`).
"""

import asyncio
import os
import socket
import threading
import uuid

import pytest
import redis.asyncio as aioredis

from gateway.app.clock import FakeClock
from gateway.app.limits.rate_limiter import RateLimitDenied, RateLimiter, ScopeLimits


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def fakeredis_tcp_port():
    from fakeredis import TcpFakeServer

    port = _free_port()
    server = TcpFakeServer(("127.0.0.1", port), server_type="redis")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()
    server.server_close()


async def test_100_concurrent_over_tcp_fakeredis_exactly_50(fakeredis_tcp_port):
    client = aioredis.Redis(port=fakeredis_tcp_port, socket_timeout=5)
    limiter = RateLimiter(client, FakeClock(), concurrency_ttl_s=60)
    key = ScopeLimits("key:tcp", rpm=50)
    team = ScopeLimits("team:tcp")

    async def attempt() -> bool:
        try:
            await limiter.acquire(key, team, est_tokens=1)
            return True
        except RateLimitDenied:
            return False

    results = await asyncio.gather(*[attempt() for _ in range(100)])
    assert sum(results) == 50
    await client.aclose()


@pytest.mark.redis
async def test_100_concurrent_real_redis_exactly_50():
    url = os.environ.get("MODELMESH_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
    client = aioredis.Redis.from_url(url, socket_connect_timeout=0.5)
    try:
        await client.ping()
    except Exception:  # noqa: BLE001 - Redis real indisponível: teste ignorado
        await client.aclose()
        pytest.skip(f"Redis real indisponível em {url}")
    limiter = RateLimiter(client, FakeClock(), concurrency_ttl_s=60)
    namespace = f"test:{uuid.uuid4().hex}"
    key = ScopeLimits(f"key:{namespace}", rpm=50)
    team = ScopeLimits(f"team:{namespace}")

    async def attempt() -> bool:
        try:
            await limiter.acquire(key, team, est_tokens=1)
            return True
        except RateLimitDenied:
            return False

    attempts = [asyncio.create_task(attempt()) for _ in range(100)]
    try:
        results = await asyncio.gather(*attempts, return_exceptions=True)
        failure = next((result for result in results if isinstance(result, BaseException)), None)
        if failure is not None:
            raise failure
        assert sum(results) == 50
    finally:
        if any(not task.done() for task in attempts):
            await asyncio.gather(*attempts, return_exceptions=True)
        try:
            async for redis_key in client.scan_iter(
                match=f"rl:*:test:{namespace.split(':', 1)[1]}:*"
            ):
                await client.delete(redis_key)
        finally:
            await client.aclose()
