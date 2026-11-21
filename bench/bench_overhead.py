"""Benchmark de overhead do proxy: directo ao mock vs gateway, com e sem fallback.

Usa servidores HTTP reais (uvicorn em threads) em localhost. Providers SIMULADOS (mock).
Cada cenário: N pedidos, concorrência C, após um aquecimento. Mede p50/p95/p99 do cliente.

Execução: `python -m bench.bench_overhead --requests 400 --concurrency 8`
O relatório (JSON) vai para bench/results/overhead-report.json e inclui hardware, data e commit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from tests.live_support import ThreadServer, create_schema_sync, free_port, sqlite_url  # noqa: E402
from tests.support import ADMIN_TOKEN, default_policy  # noqa: E402

BODY = {
    "model": "mock-small",
    "messages": [{"role": "user", "content": "benchmark"}],
    "max_tokens": 8,
}
ADMIN = {"authorization": f"Bearer {ADMIN_TOKEN}"}


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "desconhecido"


def percentile(samples: list[float], pct: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def summarize(samples_ms: list[float], errors: int) -> dict:
    return {
        "n": len(samples_ms),
        "errors": errors,
        "p50_ms": round(percentile(samples_ms, 50), 3),
        "p95_ms": round(percentile(samples_ms, 95), 3),
        "p99_ms": round(percentile(samples_ms, 99), 3),
        "mean_ms": round(statistics.fmean(samples_ms), 3),
    }


async def run_load(
    url: str, headers: dict, total: int, concurrency: int
) -> tuple[list[float], int]:
    samples: list[float] = []
    errors = 0
    semaphore = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=10, limits=limits) as client:

        async def one() -> None:
            nonlocal errors
            async with semaphore:
                start = time.perf_counter()
                response = await client.post(url, json=BODY, headers=headers)
                elapsed = (time.perf_counter() - start) * 1000
                if response.status_code == 200:
                    samples.append(elapsed)
                else:
                    errors += 1

        await asyncio.gather(*[one() for _ in range(total)])
    return samples, errors


async def set_mock(ctrl: str, **profile) -> None:  # noqa: ANN003
    async with httpx.AsyncClient(timeout=5) as client:
        (
            await client.put(f"{ctrl}/control/profile", json={"seed": 1, **profile})
        ).raise_for_status()


async def main_async(total: int, concurrency: int, warmup: int) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="mm-bench-"))
    ports = {"a": free_port(), "b": free_port(), "gw": free_port()}
    db = sqlite_url(tmp)
    create_schema_sync(db)
    os.environ.update(
        {
            "MM_DB_URL": db,
            "MM_ADMIN_TOKEN": ADMIN_TOKEN,
            "MM_MOCK_A_URL": f"http://127.0.0.1:{ports['a']}/v1",
            "MM_MOCK_A_CTRL": f"http://127.0.0.1:{ports['a']}",
            "MM_MOCK_B_URL": f"http://127.0.0.1:{ports['b']}/v1",
            "MM_MOCK_B_CTRL": f"http://127.0.0.1:{ports['b']}",
            "MM_MOCK_A": json.dumps({"seed": 1}),
            "MM_MOCK_B": json.dumps({"seed": 2}),
        }
    )
    servers = [
        ThreadServer("tests.live_support:build_mock_a", ports["a"]),
        ThreadServer("tests.live_support:build_mock_b", ports["b"]),
        ThreadServer("tests.live_support:build_gateway", ports["gw"]),
    ]
    for server in servers:
        server.start()
    gw = f"http://127.0.0.1:{ports['gw']}"
    try:
        async with httpx.AsyncClient(base_url=gw, timeout=10) as admin:
            await admin.post("/admin/teams", json={"id": "bench", "name": "Bench"}, headers=ADMIN)
            await admin.put(
                "/admin/policies/bench", headers=ADMIN, json=default_policy(retries_per_hop=0)
            )
            key = (
                await admin.post(
                    "/admin/keys", json={"team_id": "bench", "name": "b"}, headers=ADMIN
                )
            ).json()["key"]
        auth = {"authorization": f"Bearer {key}"}
        direct_url = f"http://127.0.0.1:{ports['a']}/v1/chat/completions"
        gateway_url = f"{gw}/v1/chat/completions"

        scenarios: dict[str, dict] = {}
        await set_mock(f"http://127.0.0.1:{ports['a']}")
        await run_load(direct_url, auth, warmup, concurrency)
        samples, errors = await run_load(direct_url, auth, total, concurrency)
        scenarios["direct_to_mock_a"] = summarize(samples, errors)

        await run_load(gateway_url, auth, warmup, concurrency)
        samples, errors = await run_load(gateway_url, auth, total, concurrency)
        scenarios["gateway_no_fallback"] = summarize(samples, errors)

        await set_mock(f"http://127.0.0.1:{ports['a']}", error_rate=1.0)
        samples, errors = await run_load(gateway_url, auth, total, concurrency)
        scenarios["gateway_with_fallback_a_fails"] = summarize(samples, errors)
        await set_mock(f"http://127.0.0.1:{ports['a']}")
    finally:
        for server in servers:
            server.stop()
    return scenarios


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark de overhead do ModelMesh (mock)")
    parser.add_argument("--requests", type=int, default=400)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--warmup", type=int, default=40)
    args = parser.parse_args()

    started = datetime.now(UTC)
    scenarios = asyncio.run(main_async(args.requests, args.concurrency, args.warmup))
    overhead = {
        "gateway_vs_direct_p50_ms": round(
            scenarios["gateway_no_fallback"]["p50_ms"] - scenarios["direct_to_mock_a"]["p50_ms"], 3
        ),
        "gateway_vs_direct_p95_ms": round(
            scenarios["gateway_no_fallback"]["p95_ms"] - scenarios["direct_to_mock_a"]["p95_ms"], 3
        ),
        "gateway_vs_direct_p99_ms": round(
            scenarios["gateway_no_fallback"]["p99_ms"] - scenarios["direct_to_mock_a"]["p99_ms"], 3
        ),
    }
    report = {
        "providers": "mock",
        "date_utc": started.isoformat(),
        "commit": _git("rev-parse", "--short", "HEAD"),
        "worktree_dirty": bool(_git("status", "--porcelain")),
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor() or "desconhecido",
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
        },
        "load": {
            "requests_per_scenario": args.requests,
            "concurrency": args.concurrency,
            "warmup": args.warmup,
            "client": "httpx.AsyncClient",
            "transport": "HTTP localhost",
        },
        "scenarios": scenarios,
        "overhead": overhead,
        "limitations": [
            "Providers simulados (mock) em localhost; latência de rede real não medida.",
            "Redis é fakeredis em processo (não é Redis real): o custo de rede do Redis não entra.",
            "Medição numa só máquina, sem isolamento de CPU; o ruído é o do sistema operativo.",
        ],
    }
    out = ROOT / "bench" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "overhead-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({"scenarios": scenarios, "overhead": overhead}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
