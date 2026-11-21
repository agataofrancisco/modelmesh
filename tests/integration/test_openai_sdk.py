"""Tarefa 3.2: o SDK oficial da OpenAI, apontado ao gateway com os mocks, obtém resposta válida.

Usa servidores HTTP reais (uvicorn em threads), não transporte em processo.
"""

import json
import os

import pytest

from tests.live_support import ThreadServer, create_schema_sync, free_port, sqlite_url
from tests.support import ADMIN_TOKEN, default_policy

openai = pytest.importorskip("openai")


@pytest.fixture
def live(tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    mock_a_port, mock_b_port, gw_port = free_port(), free_port(), free_port()
    create_schema_sync(sqlite_url(tmp_path))
    monkeypatch.setenv("MM_DB_URL", sqlite_url(tmp_path))
    monkeypatch.setenv("MM_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("MM_MOCK_A", json.dumps({"seed": 3}))
    monkeypatch.setenv("MM_MOCK_B", json.dumps({"seed": 5}))
    monkeypatch.setenv("MM_MOCK_A_URL", f"http://127.0.0.1:{mock_a_port}/v1")
    monkeypatch.setenv("MM_MOCK_A_CTRL", f"http://127.0.0.1:{mock_a_port}")
    monkeypatch.setenv("MM_MOCK_B_URL", f"http://127.0.0.1:{mock_b_port}/v1")
    monkeypatch.setenv("MM_MOCK_B_CTRL", f"http://127.0.0.1:{mock_b_port}")
    servers = [
        ThreadServer("tests.live_support:build_mock_a", mock_a_port),
        ThreadServer("tests.live_support:build_mock_b", mock_b_port),
        ThreadServer("tests.live_support:build_gateway", gw_port),
    ]
    for server in servers:
        server.start()
    yield {"gateway": f"http://127.0.0.1:{gw_port}", "admin": ADMIN_TOKEN}
    for server in servers:
        server.stop()


def test_official_openai_sdk_against_gateway(live):
    import httpx

    admin = {"authorization": f"Bearer {live['admin']}"}
    base = live["gateway"]
    with httpx.Client(base_url=base, timeout=10) as http:
        assert (
            http.post(
                "/admin/teams", json={"id": "suporte", "name": "S"}, headers=admin
            ).status_code
            == 201
        )
        assert (
            http.put("/admin/policies/suporte", json=default_policy(), headers=admin).status_code
            == 200
        )
        key = http.post(
            "/admin/keys", json={"team_id": "suporte", "name": "sdk"}, headers=admin
        ).json()["key"]

    client = openai.OpenAI(base_url=f"{base}/v1", api_key=key, max_retries=0)
    completion = client.chat.completions.create(
        model="cheap",
        messages=[{"role": "user", "content": "Diz olá em uma palavra."}],
        max_tokens=64,
    )
    assert completion.id
    assert completion.choices[0].message.role == "assistant"
    assert completion.usage.prompt_tokens > 0
    assert completion.usage.completion_tokens > 0


def test_official_sdk_fallback_is_transparent(live):
    import httpx

    admin = {"authorization": f"Bearer {live['admin']}"}
    base = live["gateway"]
    with httpx.Client(base_url=base, timeout=10) as http:
        http.post("/admin/teams", json={"id": "dados", "name": "D"}, headers=admin)
        http.put("/admin/policies/dados", json=default_policy(retries_per_hop=0), headers=admin)
        key = http.post(
            "/admin/keys", json={"team_id": "dados", "name": "sdk"}, headers=admin
        ).json()["key"]
        # Mock A passa a falhar sempre; o SDK não deve notar a diferença.
        mock_a_ctrl = os.environ["MM_MOCK_A_CTRL"]
        with httpx.Client(timeout=5) as control:
            control.put(
                f"{mock_a_ctrl}/control/profile", json={"error_rate": 1.0, "seed": 3}
            ).raise_for_status()

    client = openai.OpenAI(base_url=f"{base}/v1", api_key=key, max_retries=0)
    raw = client.chat.completions.with_raw_response.create(
        model="mock-small", messages=[{"role": "user", "content": "oi"}]
    )
    assert raw.headers["x-modelmesh-fallback-path"] == "mock_a->mock_b"
    assert raw.parse().choices[0].message.content
