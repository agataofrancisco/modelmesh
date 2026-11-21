"""Tarefas 5.1-5.3: rate limit atómico, reserva/reconciliação de orçamento, sweeper, fail-closed.

Nota: estes testes usam fakeredis em processo (Lua real via lupa). A prova de concorrência
com sockets reais está em test_fakeredis_tcp.py (servidor TCP fakeredis, NÃO é Redis real).
"""

import asyncio
from datetime import date
from decimal import Decimal

import fakeredis
from sqlalchemy import func, select

from gateway.app.accounting.prices import PriceBook, PriceEntry
from gateway.app.budget.ledger import BudgetExceeded, BudgetLedger, BudgetScope
from gateway.app.budget.sweeper import sweep_once
from gateway.app.clock import FakeClock
from gateway.app.limits.rate_limiter import RateLimitDenied, RateLimiter, ScopeLimits
from gateway.app.store.models import UsageRecord
from tests.conftest import build_env
from tests.support import ADMIN_TOKEN, default_policy

ADMIN = {"authorization": f"Bearer {ADMIN_TOKEN}"}
BODY = {"model": "mock-small", "messages": [{"role": "user", "content": "x"}], "max_tokens": 8}


async def _team(env, policy, **key_limits):
    await env.client.post("/admin/teams", json={"id": "suporte", "name": "S"}, headers=ADMIN)
    await env.client.put("/admin/policies/suporte", json=policy, headers=ADMIN)
    created = await env.client.post(
        "/admin/keys", json={"team_id": "suporte", "name": "k", **key_limits}, headers=ADMIN
    )
    return {"authorization": f"Bearer {created.json()['key']}"}


async def _close(env):
    await env.client.aclose()
    await env.http.aclose()
    await env.engine.dispose()
    await env.redis.aclose()


async def test_rpm_100_concurrent_exactly_50_accepted(tmp_path):
    env = await build_env(tmp_path)
    try:
        headers = await _team(env, default_policy(), rpm_limit=50)
        responses = await asyncio.gather(
            *[
                env.client.post("/v1/chat/completions", json=BODY, headers=headers)
                for _ in range(100)
            ]
        )
        codes = [r.status_code for r in responses]
        assert codes.count(200) == 50
        assert codes.count(429) == 50
        limited = next(r for r in responses if r.status_code == 429)
        assert limited.json()["error"]["code"] == "rate_limited"
        assert int(limited.headers["retry-after"]) >= 1
    finally:
        await _close(env)


async def test_concurrency_limit_released_even_on_error(tmp_path):
    env = await build_env(tmp_path)
    try:
        headers = await _team(env, default_policy(), concurrency_limit=1)
        env.mock_a.set_profile(env.mock_a.profile.model_copy(update={"error_rate": 1.0}))
        env.mock_b.set_profile(env.mock_b.profile.model_copy(update={"error_rate": 1.0}))
        first = await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
        assert first.status_code == 503
        second = await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
        assert second.status_code == 503  # não ficou preso com 429 de concorrência
    finally:
        await _close(env)


async def test_rate_limiter_direct_concurrency_and_release():
    redis = fakeredis.FakeAsyncRedis()
    limiter = RateLimiter(redis, FakeClock(), concurrency_ttl_s=60)
    key = ScopeLimits("key:t", concurrency=2)
    team = ScopeLimits("team:t")
    try:
        first = await limiter.acquire(key, team, est_tokens=1)
        await limiter.acquire(key, team, est_tokens=1)
        try:
            await limiter.acquire(key, team, est_tokens=1)
            raise AssertionError("devia recusar")
        except RateLimitDenied as denied:
            assert denied.kind == "concurrency"
        await limiter.release(first)
        await limiter.acquire(key, team, est_tokens=1)
    finally:
        await redis.aclose()


async def test_tpm_limit_rejects_when_minute_budget_spent():
    redis = fakeredis.FakeAsyncRedis()
    limiter = RateLimiter(redis, FakeClock(), concurrency_ttl_s=60)
    key = ScopeLimits("key:x", tpm=100)
    try:
        await limiter.acquire(key, ScopeLimits("team:x"), est_tokens=80)
        try:
            await limiter.acquire(key, ScopeLimits("team:x"), est_tokens=80)
            raise AssertionError("devia recusar por TPM")
        except RateLimitDenied as denied:
            assert denied.kind == "tpm"
    finally:
        await redis.aclose()


async def test_reserve_settle_and_release_roundtrip():
    redis = fakeredis.FakeAsyncRedis()
    ledger = BudgetLedger(redis, reservation_ttl_s=60)
    try:
        res = await ledger.reserve(
            BudgetScope("key:a", 1_000_000),
            BudgetScope("team:a", 1_000_000),
            estimate_micro=300_000,
            now_ms=1_700_000_000_000,
            payload={"request_id": "r1"},
        )
        assert (await ledger.snapshot("team:a", res.period))["reserved_micro"] == 300_000
        assert await ledger.settle(res, real_micro=120_000)
        snap = await ledger.snapshot("team:a", res.period)
        assert snap == {"spent_micro": 120_000, "reserved_micro": 0}
        assert not await ledger.settle(res, real_micro=0)  # idempotente
    finally:
        await redis.aclose()


async def test_budget_over_team_limit_rejected():
    redis = fakeredis.FakeAsyncRedis()
    ledger = BudgetLedger(redis, reservation_ttl_s=60)
    try:
        await ledger.reserve(
            BudgetScope("key:b", -1),
            BudgetScope("team:b", 500_000),
            estimate_micro=400_000,
            now_ms=1_700_000_000_000,
            payload={},
        )
        try:
            await ledger.reserve(
                BudgetScope("key:b", -1),
                BudgetScope("team:b", 500_000),
                estimate_micro=200_000,
                now_ms=1_700_000_000_000,
                payload={},
            )
            raise AssertionError("devia recusar")
        except BudgetExceeded as exc:
            assert exc.scope == "team"
    finally:
        await redis.aclose()


async def test_orphan_reservation_expires_and_is_recorded(tmp_path):
    """Simula um crash entre reservar e reconciliar: após o TTL o sweeper cobra a estimativa."""
    env = await build_env(tmp_path)
    try:
        now = env.clock.wall_ms()
        ledger = env.services.budget
        res = await ledger.reserve(
            BudgetScope("key:o", 10_000_000),
            BudgetScope("team:o", -1),
            estimate_micro=250_000,
            now_ms=now,
            payload={
                "request_id": "crash",
                "team_id": "o",
                "key_id": "k",
                "key_prefix": "mm_live_abcdefgh",
                "model_requested": "m",
                "trace_id": None,
            },
        )
        assert (await ledger.snapshot("team:o", res.period))["reserved_micro"] == 250_000
        assert await sweep_once(env.services, now_ms=now) == 0  # TTL ainda não passou
        assert await sweep_once(env.services, now_ms=now + 121_000) == 1
        snap = await ledger.snapshot("team:o", res.period)
        assert snap == {"spent_micro": 250_000, "reserved_micro": 0}
        async with env.session_factory() as session:
            row = (
                await session.execute(select(UsageRecord).where(UsageRecord.request_id == "crash"))
            ).scalar_one()
            assert row.status == "orphan_released" and row.usage_estimated is True
    finally:
        await _close(env)


async def test_200_concurrent_requests_never_exceed_budget(tmp_path):
    """Orçamento de 1 USD com preços altos: cada pedido estima ~0.1 USD (fakeredis em processo)."""
    expensive = PriceBook(
        [
            PriceEntry(p, m, Decimal("5000"), Decimal("5000"), "USD", date(2026, 1, 1), "teste")
            for p in ("mock_a", "mock_b")
            for m in ("mock-small", "mock-large")
        ]
    )
    env = await build_env(tmp_path, prices=expensive)
    try:
        headers = await _team(env, default_policy(budget_usd_monthly="1"))
        responses = await asyncio.gather(
            *[
                env.client.post("/v1/chat/completions", json=BODY, headers=headers)
                for _ in range(200)
            ]
        )
        codes = [r.status_code for r in responses]
        assert codes.count(402) > 0
        assert all(
            r.json()["error"]["code"] == "budget_exceeded"
            for r in responses
            if r.status_code == 402
        )
        assert codes.count(200) >= 1
        async with env.session_factory() as session:
            spent = (
                await session.execute(select(func.coalesce(func.sum(UsageRecord.cost_real_usd), 0)))
            ).scalar_one()
        assert Decimal(spent) <= Decimal("1")
    finally:
        await _close(env)


async def test_failed_request_releases_budget_reservation(tmp_path):
    """Pedido em que todos os hops falham: a reserva volta a zero (sem gasto)."""
    env = await build_env(tmp_path)
    try:
        headers = await _team(env, default_policy(budget_usd_monthly="5", retries_per_hop=0))
        env.mock_a.set_profile(env.mock_a.profile.model_copy(update={"error_rate": 1.0}))
        env.mock_b.set_profile(env.mock_b.profile.model_copy(update={"error_rate": 1.0}))
        response = await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
        assert response.status_code == 503
        period = (await env.client.get("/admin/budgets?team=suporte", headers=ADMIN)).json()[
            "period"
        ]
        snap = await env.services.budget.snapshot("team:suporte", period)
        assert snap == {"spent_micro": 0, "reserved_micro": 0}
    finally:
        await _close(env)
