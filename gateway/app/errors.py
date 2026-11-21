"""Erros do gateway no formato de erro da OpenAI, com `type` e `code` estáveis."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

# code -> (status HTTP, type). Códigos da spec são estáveis; os demais são extensões.
ERROR_CATALOG: dict[str, tuple[int, str]] = {
    "invalid_api_key": (401, "authentication_error"),
    "forbidden": (403, "permission_error"),
    "model_not_allowed": (403, "permission_error"),
    "invalid_request": (400, "invalid_request_error"),
    "max_tokens_exceeded": (400, "invalid_request_error"),
    "streaming_not_supported": (400, "invalid_request_error"),
    "upstream_client_error": (400, "invalid_request_error"),
    "body_too_large": (413, "invalid_request_error"),
    "validation_error": (422, "invalid_request_error"),
    "not_found": (404, "invalid_request_error"),
    "conflict": (409, "invalid_request_error"),
    "rate_limited": (429, "rate_limit_error"),
    "budget_exceeded": (402, "budget_error"),
    "upstream_unavailable": (503, "server_error"),
    "timeout": (504, "server_error"),
    "pricing_missing": (503, "server_error"),
    "service_unavailable": (503, "server_error"),
    "internal_error": (500, "server_error"),
}


class GatewayError(Exception):
    """Falha previsível. `details` é serializado sem conter segredos nem conteúdo de pedidos."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        if code not in ERROR_CATALOG:
            raise ValueError(f"código de erro desconhecido: {code}")
        self.code = code
        self.status_code, self.error_type = ERROR_CATALOG[code]
        self.message = message
        self.details = details or {}
        self.headers = headers or {}
        super().__init__(message)


def error_body(
    code: str, message: str, request_id: str | None, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    status, error_type = ERROR_CATALOG[code]
    body: dict[str, Any] = {
        "message": message,
        "type": error_type,
        "param": None,
        "code": code,
        "request_id": request_id,
    }
    if details:
        body["details"] = details
    return {"error": body}


async def gateway_error_handler(request: Request, exc: GatewayError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    headers = dict(exc.headers)
    if request_id:
        headers["x-modelmesh-request-id"] = request_id
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, request_id, exc.details),
        headers=headers,
    )
