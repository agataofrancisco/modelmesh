"""Tarefas 3.1-3.2 e 4.1/4.3: endpoint de inferência, alias de classe, fallback e erros."""


from tests.support import ADMIN_TOKEN, default_policy

ADMIN = {"authorization": f"Bearer {ADMIN_TOKEN}"}
BODY = {"model": "mock-small", "messages": [{"role": "user", "content": "olá"}]}


async def setup_team(env, policy=None, **limits):
    await env.client.post("/admin/teams", json={"id": "suporte", "name": "S"}, headers=ADMIN)
    await env.client.put("/admin/policies/suporte", json=policy or default_policy(), headers=ADMIN)
    created = await env.client.post(
        "/admin/keys", json={"team_id": "suporte", "name": "k", **limits}, headers=ADMIN
    )
    return {"authorization": f"Bearer {created.json()['key']}"}


async def chat(env, headers, body=None):
    return await env.client.post("/v1/chat/completions", json=body or BODY, headers=headers)


async def test_no_key_is_401_and_never_contacts_provider(env):
    await setup_team(env)
    response = await env.client.post("/v1/chat/completions", json=BODY)
    assert response.status_code == 401
    assert env.mock_a.requests == 0 and env.mock_b.requests == 0


async def test_success_with_openai_shape_and_headers(env):
    headers = await setup_team(env)
    response = await chat(env, headers)
    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["usage"]["prompt_tokens"] > 0
    assert response.headers["x-modelmesh-provider"] == "mock_a"
    assert response.headers["x-modelmesh-fallback-path"] == "mock_a"
    assert response.headers["x-modelmesh-request-id"].startswith("req_")


async def test_class_alias_resolves_and_is_reported(env):
    headers = await setup_team(env)
    response = await chat(env, headers, {**BODY, "model": "cheap"})
    assert response.status_code == 200
    assert response.headers["x-modelmesh-model"] == "mock-small"
    assert response.headers["x-modelmesh-requested-model"] == "cheap"


async def test_model_not_allowed_is_403_without_provider_call(env):
    headers = await setup_team(env)
    response = await chat(env, headers, {**BODY, "model": "gpt-4"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "model_not_allowed"
    assert env.mock_a.requests == 0


async def test_invalid_body_is_400_openai_format(env):
    headers = await setup_team(env)
    response = await chat(env, headers, {"model": "mock-small", "messages": []})
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert env.mock_a.requests == 0 and env.mock_b.requests == 0


async def test_max_tokens_above_policy_rejected(env):
    headers = await setup_team(env)
    response = await chat(env, headers, {**BODY, "max_tokens": 10_000})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "max_tokens_exceeded"


async def test_provider_a_fails_fallback_to_b(env):
    headers = await setup_team(env)
    env.mock_a.set_profile(env.mock_a.profile.model_copy(update={"error_rate": 1.0}))
    response = await chat(env, headers)
    assert response.status_code == 200
    assert response.headers["x-modelmesh-fallback-path"] == "mock_a->mock_b"
    assert response.headers["x-modelmesh-provider"] == "mock_b"


async def test_client_error_does_not_fallback(env):
    headers = await setup_team(env)
    env.mock_a.set_profile(
        env.mock_a.profile.model_copy(update={"error_rate": 1.0, "error_statuses": [400]})
    )
    response = await chat(env, headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "upstream_client_error"
    assert env.mock_b.requests == 0


async def test_all_hops_fail_is_503_upstream_unavailable(env):
    headers = await setup_team(env, policy=default_policy(retries_per_hop=0))
    for mock in (env.mock_a, env.mock_b):
        mock.set_profile(mock.profile.model_copy(update={"error_rate": 1.0}))
    response = await chat(env, headers)
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "upstream_unavailable"
    assert error["request_id"] == response.headers["x-modelmesh-request-id"]
    assert [h["provider"] for h in error["details"]["attempted_hops"]] == ["mock_a", "mock_b"]


async def test_invalid_json_from_provider_falls_back(env):
    headers = await setup_team(env)
    env.mock_a.set_profile(env.mock_a.profile.model_copy(update={"invalid_json_rate": 1.0}))
    response = await chat(env, headers)
    assert response.status_code == 200
    assert response.headers["x-modelmesh-provider"] == "mock_b"


async def test_missing_usage_marked_as_estimated(env):
    headers = await setup_team(env)
    env.mock_a.set_profile(env.mock_a.profile.model_copy(update={"omit_usage": True}))
    response = await chat(env, headers)
    assert response.status_code == 200
    assert response.headers["x-modelmesh-usage-estimated"] == "true"


async def test_slow_provider_times_out_and_falls_back(env):
    headers = await setup_team(env, policy=default_policy(hop_timeout_ms=100, retries_per_hop=0))
    env.mock_a.set_profile(env.mock_a.profile.model_copy(update={"latency_ms": 800}))
    response = await chat(env, headers)
    assert response.status_code == 200
    assert response.headers["x-modelmesh-provider"] == "mock_b"


async def test_429_retry_after_respected_then_fallback(env):
    headers = await setup_team(env, policy=default_policy(retries_per_hop=0))
    env.mock_a.set_profile(
        env.mock_a.profile.model_copy(
            update={"error_rate": 1.0, "error_statuses": [429], "retry_after_s": 1}
        )
    )
    response = await chat(env, headers)
    assert response.status_code == 200
    assert response.headers["x-modelmesh-provider"] == "mock_b"


def _closed_port() -> int:
    """Porta livre sem servidor: o Redis real indisponível é simulado por ligação recusada."""
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def test_redis_down_fails_closed_with_503(tmp_path):
    from redis.asyncio import Redis

    from tests.conftest import build_env

    dead = Redis.from_url(f"redis://127.0.0.1:{_closed_port()}/0", socket_connect_timeout=0.5)
    env = await build_env(tmp_path, redis=dead)
    try:
        headers = await setup_team(env)
        response = await chat(env, headers)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "service_unavailable"
        assert env.mock_a.requests == 0
        ready = await env.client.get("/health/ready")
        assert ready.status_code == 503
    finally:
        await env.client.aclose()
        await env.http.aclose()
        await env.engine.dispose()
