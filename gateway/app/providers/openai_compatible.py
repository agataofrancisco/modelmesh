"""Adaptador para qualquer endpoint compatível com `POST {base_url}/chat/completions`.

Usado para os providers reais (OpenAI, OpenRouter) e para os mocks A/B. Normaliza cada
resposta ou falha para `ProviderResponse` ou `ProviderError`. Nunca regista o corpo do
pedido nem da resposta: podem conter conteúdo privado.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from gateway.app.providers.base import (
    KIND_AUTH,
    KIND_CLIENT,
    KIND_INVALID,
    KIND_TIMEOUT,
    KIND_TRANSIENT,
    Hop,
    ProviderError,
    ProviderResponse,
    Usage,
)
from gateway.app.settings import ProviderConfig


def _parse_retry_after(value: str | None) -> float | None:
    """Só o formato em segundos (inteiro ou decimal). Datas HTTP são ignoradas por simplicidade."""
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _parse_usage(payload: dict[str, Any]) -> Usage | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if isinstance(prompt, bool) or isinstance(completion, bool):
        return None
    if not isinstance(prompt, int) or not isinstance(completion, int):
        return None
    if prompt < 0 or completion < 0:
        return None
    return Usage(prompt_tokens=prompt, completion_tokens=completion)


def classify_status(status: int, retry_after: float | None) -> ProviderError:
    """Mapeia um código HTTP de erro para a taxonomia de `providers/base.py`."""
    if status == 429:
        return ProviderError(
            KIND_TRANSIENT, "rate limited upstream", status=status, retry_after_s=retry_after
        )
    if status == 408:
        return ProviderError(KIND_TIMEOUT, "upstream request timeout", status=status)
    if status in (401, 403):
        return ProviderError(KIND_AUTH, "upstream auth rejected", status=status)
    if status >= 500:
        return ProviderError(
            KIND_TRANSIENT, f"upstream {status}", status=status, retry_after_s=retry_after
        )
    return ProviderError(KIND_CLIENT, f"upstream client error {status}", status=status)


class OpenAICompatibleAdapter:
    def __init__(self, configs: dict[str, ProviderConfig], client: httpx.AsyncClient) -> None:
        self._configs = configs
        self._client = client

    def _headers(self, config: ProviderConfig) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if config.api_key_env:
            secret = os.environ.get(config.api_key_env)
            if secret:
                headers["authorization"] = f"Bearer {secret}"
        return headers

    async def chat(self, hop: Hop, body: dict[str, Any], *, timeout_s: float) -> ProviderResponse:
        config = self._configs.get(hop.provider)
        if config is None:
            raise ProviderError(KIND_CLIENT, f"provider desconhecido: {hop.provider}")
        payload = dict(body)
        payload["model"] = hop.model
        url = f"{config.base_url}/chat/completions"
        try:
            async with asyncio.timeout(timeout_s):
                response = await self._client.post(
                    url, json=payload, headers=self._headers(config), timeout=timeout_s
                )
        except TimeoutError as exc:
            raise ProviderError(KIND_TIMEOUT, "hop timeout") from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(KIND_TIMEOUT, "hop timeout") from exc
        except httpx.TransportError as exc:
            raise ProviderError(KIND_TRANSIENT, f"transport error: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            raise classify_status(
                response.status_code, _parse_retry_after(response.headers.get("retry-after"))
            )

        try:
            parsed = response.json()
        except ValueError as exc:
            raise ProviderError(KIND_INVALID, "upstream returned invalid JSON") from exc
        if not isinstance(parsed, dict) or not isinstance(parsed.get("choices"), list):
            raise ProviderError(KIND_INVALID, "upstream response without choices")
        served = parsed.get("model")
        return ProviderResponse(
            body=parsed,
            usage=_parse_usage(parsed),
            raw_model=served if isinstance(served, str) else None,
        )
