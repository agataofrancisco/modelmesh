"""Providers simulados compatíveis com OpenAI (`mock_provider_a` e `mock_provider_b`).

O comportamento é um `MockProfile` controlável em runtime por `PUT /control/profile`:
latência, taxa de erro com códigos configuráveis, 429 com Retry-After, JSON inválido,
falta de `usage`. As decisões são tomadas com `random.Random(seed)`, portanto uma amostra
com seed fixa é reprodutível. `GET /control/stats` conta pedidos recebidos, o que permite
provar que um pedido recusado no gateway nunca chegou ao provider.

Executar: `python -m gateway.app.providers.mock_server --name mock_a --port 9001`
"""

from __future__ import annotations

import argparse
import asyncio
import random
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

ALLOWED_ERROR_STATUSES = (400, 408, 429, 500, 502, 503, 504)


class MockProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latency_ms: int = Field(default=0, ge=0, le=120_000)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    error_statuses: list[int] = Field(default_factory=lambda: [503], min_length=1, max_length=8)
    retry_after_s: float | None = Field(default=None, ge=0, le=300)
    invalid_json_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    omit_usage: bool = False
    output_tokens: int = Field(default=32, ge=1, le=4_096)
    seed: int = 1

    def validate_statuses(self) -> None:
        bad = [s for s in self.error_statuses if s not in ALLOWED_ERROR_STATUSES]
        if bad:
            raise ValueError(f"códigos de erro não suportados: {bad}")


class MockState:
    def __init__(self, name: str, profile: MockProfile) -> None:
        self.name = name
        self.set_profile(profile)
        self.requests = 0
        self.errors = 0

    def set_profile(self, profile: MockProfile) -> None:
        self.profile = profile
        self.rng = random.Random(profile.seed)


def _estimate_prompt_tokens(messages: Any) -> int:
    if not isinstance(messages, list):
        return 1
    chars = 0
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            chars += len(message["content"])
    return max(1, chars // 4)


def create_mock_app(name: str, profile: MockProfile | None = None) -> FastAPI:
    app = FastAPI(title=f"mock {name}")
    state = MockState(name, profile or MockProfile())
    app.state.mock = state

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        state.requests += 1
        profile = state.profile
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse({"error": {"message": "invalid json"}}, status_code=400)
        model = payload.get("model") if isinstance(payload, dict) else None
        if profile.latency_ms:
            await asyncio.sleep(profile.latency_ms / 1000.0)
        if profile.error_rate and state.rng.random() < profile.error_rate:
            state.errors += 1
            status = state.rng.choice(profile.error_statuses)
            headers = {}
            if status == 429 and profile.retry_after_s is not None:
                headers["retry-after"] = str(profile.retry_after_s)
            return JSONResponse(
                {"error": {"message": f"mock {status}"}}, status_code=status, headers=headers
            )
        if profile.invalid_json_rate and state.rng.random() < profile.invalid_json_rate:
            state.errors += 1
            return PlainTextResponse("<html>not json", status_code=200)

        prompt_tokens = _estimate_prompt_tokens(payload.get("messages"))
        body: dict[str, Any] = {
            "id": f"chatcmpl-mock-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": f"respuesta mock de {name}"},
                    "finish_reason": "stop",
                }
            ],
        }
        if not profile.omit_usage:
            body["usage"] = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": profile.output_tokens,
                "total_tokens": prompt_tokens + profile.output_tokens,
            }
        return JSONResponse(body)

    @app.get("/control/profile")
    async def get_profile() -> dict[str, Any]:
        return state.profile.model_dump()

    @app.put("/control/profile")
    async def put_profile(request: Request) -> Any:
        try:
            profile = MockProfile.model_validate(await request.json())
            profile.validate_statuses()
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": {"message": f"perfil inválido: {exc}"}}, status_code=422)
        state.set_profile(profile)
        return profile.model_dump()

    @app.get("/control/stats")
    async def stats() -> dict[str, Any]:
        return {"name": name, "requests": state.requests, "injected_errors": state.errors}

    return app


def main() -> None:  # pragma: no cover - arranque manual
    parser = argparse.ArgumentParser(description="Provider simulado compatível com OpenAI")
    parser.add_argument("--name", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    uvicorn.run(create_mock_app(args.name), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":  # pragma: no cover
    main()
