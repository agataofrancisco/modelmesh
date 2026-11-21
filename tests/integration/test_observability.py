"""Tarefas 6.1-6.2 e 7.1-7.2: preços por data, redacção, métricas, tracing, ready e rotas."""

import json
import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from gateway.app.accounting.prices import PriceBook, PriceEntry, cost_micro
from gateway.app.accounting.redaction import redact
from gateway.app.store.models import UsageRecord
from tests.conftest import build_env
from tests.support import ADMIN_TOKEN, default_policy

ADMIN = {"authorization": f"Bearer {ADMIN_TOKEN}"}
BODY = {"model": "mock-small", "messages": [{"role": "user", "content": "olá"}]}


async def _team(env, policy=None):
    await env.client.post("/admin/teams", json={"id": "suporte", "name": "S"}, headers=ADMIN)
    await env.client.put("/admin/policies/suporte", json=policy or default_policy(), headers=ADMIN)
    created = await env.client.post(
        "/admin/keys", json={"team_id": "suporte", "name": "k"}, headers=ADMIN
    )
    return {"authorization": f"Bearer {created.json()['key']}"}


async def _close(env):
    await env.client.aclose()
    await env.http.aclose()
    await env.engine.dispose()
    await env.redis.aclose()


def _entry(on: date, input_price: str) -> PriceEntry:
    return PriceEntry(
        "mock_a", "mock-small", Decimal(input_price), Decimal("2"), "USD", on, "teste"
    )


def test_price_uses_latest_effective_date_not_after_request_date():
    book = PriceBook([_entry(date(2026, 1, 1), "1"), _entry(date(2026, 12, 1), "10")])
    assert book.price_for("mock_a", "mock-small", date(2026, 11, 20)).input_per_mtok == Decimal("1")
    assert book.price_for("mock_a", "mock-small", date(2026, 12, 2)).input_per_mtok == Decimal("10")
    assert book.price_for("mock_a", "mock-small", date(2025, 6, 1)) is None


def test_cost_worked_example_is_exact():
    # 1000 tokens de entrada a 1 USD/MTok + 500 de saída a 2 USD/MTok = 0.002 USD = 2000 micro-USD.
    entry = _entry(date(2026, 1, 1), "1")
    assert cost_micro(entry, 1000, 500) == 2000


def test_redaction_removes_email_phone_and_keys():
    text = "contacto joao.silva@example.com ou +351 912 345 678; key mm_live_" + "a" * 32
    result = redact(text)
    assert "joao.silva@example.com" not in result
    assert "912 345 678" not in result
    assert "mm_live_" + "a" * 32 not in result
    assert "2026-11-20" in redact("data 2026-11-20")


async def test_missing_price_refuses_with_pricing_missing(tmp_path):
    env = await build_env(tmp_path, prices=PriceBook())
    try:
        headers = await _team(env)
        response = await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "pricing_missing"
        assert env.mock_a.requests == 0
    finally:
        await _close(env)


async def test_usage_record_has_no_message_content_and_aggregates(tmp_path):
    env = await build_env(tmp_path)
    try:
        headers = await _team(env)
        secret = {
            "model": "mock-small",
            "messages": [{"role": "user", "content": "envia para ana@example.com, +351 912345678"}],
        }
        response = await env.client.post("/v1/chat/completions", json=secret, headers=headers)
        assert response.status_code == 200
        async with env.session_factory() as session:
            row = (await session.execute(select(UsageRecord))).scalar_one()
            dumped = json.dumps({c.name: str(getattr(row, c.name)) for c in row.__table__.columns})
        assert "ana@example.com" not in dumped and "912345678" not in dumped
        usage = (
            await env.client.get("/admin/usage?group_by=team&team=suporte", headers=ADMIN)
        ).json()
        assert usage["data"][0]["requests"] == 1
    finally:
        await _close(env)


async def test_fallback_counted_and_traceparent_shared(tmp_path, caplog):
    env = await build_env(tmp_path)
    try:
        headers = await _team(env)
        env.mock_a.set_profile(env.mock_a.profile.model_copy(update={"error_rate": 1.0}))
        trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        response = await env.client.post(
            "/v1/chat/completions",
            json=BODY,
            headers={**headers, "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01"},
        )
        assert response.status_code == 200
        assert response.headers["x-modelmesh-trace-id"] == trace_id
        # Cada pedido falhado em A é repetido uma vez (retries_per_hop=1). Com 4 falhas na janela
        # o circuito de A abre; o terceiro pedido salta A e não conta como fallback.
        second = await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
        third = await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
        assert second.headers["x-modelmesh-fallback-path"] == "mock_a->mock_b"
        assert third.headers["x-modelmesh-fallback-path"] == "mock_b"
        metrics = (await env.client.get("/metrics")).text
        fallback_lines = [
            ln for ln in metrics.splitlines() if ln.startswith("modelmesh_fallback_total{")
        ]
        assert len(fallback_lines) == 1
        assert 'from="mock_a"' in fallback_lines[0] and 'to="mock_b"' in fallback_lines[0]
        assert fallback_lines[0].endswith(" 2.0")
        assert "request_id" not in metrics
    finally:
        await _close(env)


async def test_ready_and_routes_endpoints(tmp_path):
    env = await build_env(tmp_path)
    try:
        await _team(env)
        ready = await env.client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["checks"]["providers_with_closed_circuit"] >= 1
        routes = (await env.client.get("/admin/routes?team=suporte", headers=ADMIN)).json()
        cheap = next(r for r in routes["routes"] if r["requested"] == "cheap")
        assert cheap["served_model"] == "mock-small"
        assert [h["provider"] for h in cheap["chain"]] == ["mock_a", "mock_b"]
    finally:
        await _close(env)


async def test_orphan_event_logged(tmp_path, caplog):
    from gateway.app.budget.ledger import BudgetScope
    from gateway.app.budget.sweeper import sweep_once

    env = await build_env(tmp_path)
    try:
        now = env.clock.wall_ms()
        await env.services.budget.reserve(
            BudgetScope("key:x", -1),
            BudgetScope("team:x", -1),
            estimate_micro=1,
            now_ms=now,
            payload={"request_id": "r", "team_id": "x"},
        )
        with caplog.at_level(logging.WARNING, logger="modelmesh.sweeper"):
            await sweep_once(env.services, now_ms=now + 200_000)
        assert "orphan_reservation_released" in caplog.text
    finally:
        await _close(env)
