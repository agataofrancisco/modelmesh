"""`POST /v1/chat/completions`: endpoint de inferência compatível com a API da OpenAI."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from gateway.app.api.schemas import ChatCompletionRequest
from gateway.app.auth.dependencies import Principal, authenticate_inference
from gateway.app.errors import GatewayError

router = APIRouter(prefix="/v1", tags=["inference"])


def _first_validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "pedido inválido"
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", ()))
    return f"{location}: {first.get('msg', 'inválido')}" if location else str(first.get("msg"))


@router.post("/chat/completions")
async def chat_completions(
    request: Request, principal: Principal = Depends(authenticate_inference)
) -> JSONResponse:
    services = request.app.state.services
    limit = services.settings.max_body_bytes

    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise GatewayError("body_too_large", "corpo do pedido acima do limite")
    raw: bytes = await request.body()
    if len(raw) > limit:
        raise GatewayError("body_too_large", "corpo do pedido acima do limite")

    try:
        payload: Any = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise GatewayError("invalid_request", "corpo não é JSON válido") from exc
    if not isinstance(payload, dict):
        raise GatewayError("invalid_request", "o corpo deve ser um objeto JSON")
    if payload.get("stream") is True:
        raise GatewayError("streaming_not_supported", "streaming não suportado nesta versão")
    if (
        isinstance(payload.get("messages"), list)
        and len(payload["messages"]) > services.settings.max_messages
    ):
        raise GatewayError("invalid_request", "demasiadas mensagens no pedido")

    try:
        chat_request = ChatCompletionRequest.model_validate(payload)
    except ValidationError as exc:
        raise GatewayError("invalid_request", _first_validation_message(exc)) from exc

    request_id = request.state.request_id
    result = await request.app.state.pipeline.handle(chat_request, principal, request_id=request_id)
    return JSONResponse(content=result.body, headers=result.headers)
