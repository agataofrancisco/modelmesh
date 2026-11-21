"""Cenários de chaos do ModelMesh. Cada cenário tem uma asserção automática; falha -> exit 1.

Execução: `python -m chaos.run_chaos` (a partir da raiz do repositório).

Limitações (incluídas no relatório):
- providers: mock (mock_provider_a/b, em processo via transporte ASGI; sem rede real).
- Redis: fakeredis em processo (FakeAsyncRedis, Lua via lupa), NÃO é Redis real.
  O cenário "Redis indisponível" usa uma porta sem servidor.
"""

from __future__ import annotations

import asyncio
import json
import platform
import socket
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from gateway.app.store.models import UsageRecord  # noqa: E402
from tests.conftest import build_env  # noqa: E402
from tests.support import ADMIN_TOKEN, default_policy  # noqa: E402

ADMIN = {"authorization": f"Bearer {ADMIN_TOKEN}"}
BODY = {"model": "mock-small", "messages": [{"role": "user", "content": "chaos"}], "max_tokens": 8}


@dataclass
class Result:
    scenario: str
    passed: bool
    detail: str


async def _team(env, policy=None, **limits):  # noqa: ANN001, ANN202
    await env.client.post("/admin/teams", json={"id": "chaos", "name": "Chaos"}, headers=ADMIN)
    await env.client.put("/admin/policies/chaos", json=policy or default_policy(), headers=ADMIN)
    key = (
        await env.client.post(
            "/admin/keys", json={"team_id": "chaos", "name": "c", **limits}, headers=ADMIN
        )
    ).json()["key"]
    return {"authorization": f"Bearer {key}"}


def _profile(mock, **update):  # noqa: ANN001, ANN202
    mock.set_profile(mock.profile.model_copy(update=update))


async def _close(env) -> None:  # noqa: ANN001
    await env.client.aclose()
    await env.http.aclose()
    await env.engine.dispose()
    await env.redis.aclose()


async def scenario_a_fails_b_answers(tmp: Path) -> Result:
    env = await build_env(tmp)
    try:
        headers = await _team(env)
        _profile(env.mock_a, error_rate=1.0)
        r = await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
        ok = r.status_code == 200 and r.headers.get("x-modelmesh-fallback-path") == "mock_a->mock_b"
        return Result(
            "A falha -> B responde",
            ok,
            f"status={r.status_code} path={r.headers.get('x-modelmesh-fallback-path')}",
        )
    finally:
        await _close(env)


async def scenario_both_fail(tmp: Path) -> Result:
    env = await build_env(tmp)
    try:
        headers = await _team(env, policy=default_policy(retries_per_hop=0))
        _profile(env.mock_a, error_rate=1.0)
        _profile(env.mock_b, error_rate=1.0)
        r = await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
        body = r.json()["error"]
        ok = (
            r.status_code == 503
            and body["code"] == "upstream_unavailable"
            and body["request_id"] == r.headers.get("x-modelmesh-request-id")
        )
        return Result("Ambos falham -> 503 com request_id", ok, f"status={r.status_code}")
    finally:
        await _close(env)


async def scenario_429_storm(tmp: Path) -> Result:
    env = await build_env(tmp)
    try:
        headers = await _team(env, policy=default_policy(retries_per_hop=1))
        _profile(env.mock_a, error_rate=1.0, error_statuses=[429], retry_after_s=0.01)
        _profile(env.mock_b, error_rate=1.0, error_statuses=[429], retry_after_s=0.01)
        responses = [
            await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
            for _ in range(20)
        ]
        envelopes = all("error" in r.json() for r in responses if r.status_code != 200)
        codes = sorted({r.status_code for r in responses})
        ok = envelopes and all(c in (200, 429, 503) for c in codes)
        return Result("Tempestade de 429", ok, f"status_codes={codes}")
    finally:
        await _close(env)


async def scenario_slow_provider(tmp: Path) -> Result:
    env = await build_env(tmp)
    try:
        headers = await _team(
            env, policy=default_policy(hop_timeout_ms=100, timeout_ms=1000, retries_per_hop=0)
        )
        _profile(env.mock_a, latency_ms=600)
        start = time.monotonic()
        r = await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
        elapsed_ms = (time.monotonic() - start) * 1000
        ok = (
            r.status_code == 200
            and r.headers.get("x-modelmesh-provider") == "mock_b"
            and elapsed_ms < 1000
        )
        return Result("Provider lento", ok, f"status={r.status_code} elapsed_ms={elapsed_ms:.0f}")
    finally:
        await _close(env)


async def scenario_invalid_json(tmp: Path) -> Result:
    env = await build_env(tmp)
    try:
        headers = await _team(env)
        _profile(env.mock_a, invalid_json_rate=1.0)
        r = await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
        ok = r.status_code == 200 and r.headers.get("x-modelmesh-provider") == "mock_b"
        return Result("JSON inválido", ok, f"status={r.status_code}")
    finally:
        await _close(env)


async def scenario_missing_usage(tmp: Path) -> Result:
    env = await build_env(tmp)
    try:
        headers = await _team(env)
        _profile(env.mock_a, omit_usage=True)
        r = await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
        ok = r.status_code == 200 and r.headers.get("x-modelmesh-usage-estimated") == "true"
        return Result("Usage ausente", ok, f"status={r.status_code}")
    finally:
        await _close(env)


async def scenario_redis_down(tmp: Path) -> Result:
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    dead = Redis.from_url(f"redis://127.0.0.1:{port}/0", socket_connect_timeout=0.5)
    env = await build_env(tmp, redis=dead)
    try:
        headers = await _team(env)
        r = await env.client.post("/v1/chat/completions", json=BODY, headers=headers)
        ok = (
            r.status_code == 503
            and r.json()["error"]["code"] == "service_unavailable"
            and env.mock_a.requests == 0
        )
        return Result("Redis indisponível (fail-closed)", ok, f"status={r.status_code}")
    finally:
        await _close(env)


async def scenario_budget_200_concurrent(tmp: Path) -> Result:
    from datetime import date

    from gateway.app.accounting.prices import PriceBook, PriceEntry

    expensive = PriceBook(
        [
            PriceEntry(p, m, Decimal("5000"), Decimal("5000"), "USD", date(2026, 1, 1), "chaos")
            for p in ("mock_a", "mock_b")
            for m in ("mock-small", "mock-large")
        ]
    )
    env = await build_env(tmp, prices=expensive)
    try:
        headers = await _team(env, policy=default_policy(budget_usd_monthly="1"))
        responses = await asyncio.gather(
            *[
                env.client.post("/v1/chat/completions", json=BODY, headers=headers)
                for _ in range(200)
            ]
        )
        async with env.session_factory() as session:
            spent = (
                await session.execute(select(func.coalesce(func.sum(UsageRecord.cost_real_usd), 0)))
            ).scalar_one()
        accepted = sum(1 for r in responses if r.status_code == 200)
        rejected = sum(1 for r in responses if r.status_code == 402)
        ok = Decimal(spent) <= Decimal("1") and rejected > 0
        return Result(
            "Orçamento de 1 USD sob 200 pedidos concorrentes",
            ok,
            f"accepted={accepted} rejected_402={rejected} spent_usd={Decimal(spent)}",
        )
    finally:
        await _close(env)


SCENARIOS = [
    scenario_a_fails_b_answers,
    scenario_both_fail,
    scenario_429_storm,
    scenario_slow_provider,
    scenario_invalid_json,
    scenario_missing_usage,
    scenario_redis_down,
    scenario_budget_200_concurrent,
]


async def run_all(tmp: Path) -> list[Result]:
    results = []
    for scenario in SCENARIOS:
        try:
            sub = tmp / scenario.__name__
            sub.mkdir(parents=True, exist_ok=True)
            results.append(await scenario(sub))
        except Exception as exc:  # noqa: BLE001 - um cenário partido conta como falha
            results.append(
                Result(scenario.__name__, False, f"excepção: {type(exc).__name__}: {exc}")
            )
    return results


def _fakeredis_tcp_note() -> str:
    return "fakeredis em processo (FakeAsyncRedis com Lua via lupa); não é Redis real"


def main() -> int:
    from fakeredis import TcpFakeServer  # noqa: F401 - disponível para os cenários com Redis falso

    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        results = asyncio.run(run_all(Path(tmp)))
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "providers": "mock",
        "redis_backend": _fakeredis_tcp_note(),
        "transport": "ASGI em processo (sem sockets)",
        "machine": platform.platform(),
        "python": platform.python_version(),
        "duration_s": round(time.time() - started, 2),
        "limitations": [
            "Providers simulados; não extrapolar para providers reais.",
            "Redis real não disponível neste ambiente: cenários de concorrência usam fakeredis.",
            "Sem Docker: o stack Prometheus/Grafana não foi exercitado.",
        ],
        "results": [asdict(r) for r in results],
        "all_passed": all(r.passed for r in results),
    }
    out_dir = ROOT / "chaos" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "chaos-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for r in results:
        print(f"[{'PASS' if r.passed else 'FAIL'}] {r.scenario}: {r.detail}")
    print(f"providers=mock redis={_fakeredis_tcp_note()} all_passed={report['all_passed']}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
