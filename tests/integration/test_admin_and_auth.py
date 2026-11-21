"""Tarefas 1.3, 2.2 e 2.3: health, chaves (mostradas uma vez, revogação) e administração."""

from tests.support import ADMIN_TOKEN, default_policy

ADMIN = {"authorization": f"Bearer {ADMIN_TOKEN}"}


async def test_health_live(env):
    response = await env.client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_admin_requires_token(env):
    assert (await env.client.get("/admin/teams")).status_code == 401
    assert (
        await env.client.get("/admin/teams", headers={"authorization": "Bearer nope"})
    ).status_code == 401


async def test_inference_key_cannot_access_admin(env):
    await env.client.post("/admin/teams", json={"id": "suporte", "name": "S"}, headers=ADMIN)
    key = (
        await env.client.post(
            "/admin/keys", json={"team_id": "suporte", "name": "k"}, headers=ADMIN
        )
    ).json()["key"]
    response = await env.client.get("/admin/teams", headers={"authorization": f"Bearer {key}"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_key_shown_once_and_only_prefix_listed(env):
    await env.client.post("/admin/teams", json={"id": "suporte", "name": "S"}, headers=ADMIN)
    created = await env.client.post(
        "/admin/keys", json={"team_id": "suporte", "name": "k"}, headers=ADMIN
    )
    assert created.status_code == 201
    body = created.json()
    assert body["key"].startswith("mm_live_") and len(body["key"]) == 40
    assert body["prefix"] == body["key"][:16]
    listed = (await env.client.get("/admin/keys?team=suporte", headers=ADMIN)).json()["data"]
    assert listed[0]["prefix"] == body["prefix"]
    assert "key" not in listed[0] and "key_hash" not in listed[0]


async def test_revoked_key_gets_401(env):
    await env.client.post("/admin/teams", json={"id": "suporte", "name": "S"}, headers=ADMIN)
    await env.client.put("/admin/policies/suporte", json=default_policy(), headers=ADMIN)
    created = (
        await env.client.post(
            "/admin/keys", json={"team_id": "suporte", "name": "k"}, headers=ADMIN
        )
    ).json()
    key = created["key"]
    body = {"model": "mock-small", "messages": [{"role": "user", "content": "oi"}]}
    assert (
        await env.client.post(
            "/v1/chat/completions", json=body, headers={"authorization": f"Bearer {key}"}
        )
    ).status_code == 200
    revoked = await env.client.post(f"/admin/keys/{created['id']}/revoke", headers=ADMIN)
    assert revoked.json()["status"] == "revoked"
    response = await env.client.post(
        "/v1/chat/completions", json=body, headers={"authorization": f"Bearer {key}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


async def test_invalid_policy_rejected_and_previous_kept(env):
    await env.client.post("/admin/teams", json={"id": "suporte", "name": "S"}, headers=ADMIN)
    ok = await env.client.put("/admin/policies/suporte", json=default_policy(), headers=ADMIN)
    assert ok.json()["version"] == 1
    bad = default_policy()
    bad["models"]["mock-small"]["chain"] = [{"provider": "inexistente", "model": "x"}]
    response = await env.client.put("/admin/policies/suporte", json=bad, headers=ADMIN)
    assert response.status_code == 422
    current = (await env.client.get("/admin/policies/suporte", headers=ADMIN)).json()
    assert current["version"] == 1


async def test_policy_unknown_provider_is_422_with_details(env):
    await env.client.post("/admin/teams", json={"id": "suporte", "name": "S"}, headers=ADMIN)
    bad = default_policy()
    bad["models"]["mock-small"]["chain"] = [{"provider": "nope", "model": "x"}]
    response = await env.client.put("/admin/policies/suporte", json=bad, headers=ADMIN)
    assert response.status_code == 422
    assert response.json()["error"]["details"]["unknown_providers"] == ["nope"]


async def test_duplicate_team_conflicts(env):
    await env.client.post("/admin/teams", json={"id": "dados", "name": "D"}, headers=ADMIN)
    response = await env.client.post(
        "/admin/teams", json={"id": "dados", "name": "D"}, headers=ADMIN
    )
    assert response.status_code == 409
