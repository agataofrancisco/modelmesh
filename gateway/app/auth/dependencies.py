"""Autenticação: chaves virtuais para inferência, token separado para administração.

- Inferência: `Authorization: Bearer mm_live_...` com chave ativa. Sem chave válida -> 401.
- Administração: token de admin (env `MODELMESH_ADMIN_TOKEN`). Uma chave virtual em `/admin/*`
  devolve 403 (não é a credencial errada, é a credencial de um papel sem permissão).
  Sem token configurado, a administração fica fechada (fail-closed).
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from decimal import Decimal

from fastapi import Request
from sqlalchemy import select

from gateway.app.auth.keys import hash_key, looks_like_virtual_key
from gateway.app.errors import GatewayError
from gateway.app.store import repository
from gateway.app.store.models import Team


@dataclass(frozen=True)
class Principal:
    key_id: str
    key_prefix: str
    team_id: str
    rpm_limit: int | None
    tpm_limit: int | None
    concurrency_limit: int | None
    budget_usd: Decimal | None


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not isinstance(header, str):
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def authenticate_inference(request: Request) -> Principal:
    services = request.app.state.services
    token = _bearer(request)
    if token is None or not looks_like_virtual_key(token):
        raise GatewayError("invalid_api_key", "chave de API em falta ou inválida")

    async with services.session_factory() as session:
        record = await repository.get_key_by_hash(session, hash_key(token))
    if record is None or record.status != "active":
        raise GatewayError("invalid_api_key", "chave de API em falta ou inválida")
    return Principal(
        key_id=record.id,
        key_prefix=record.prefix,
        team_id=record.team_id,
        rpm_limit=record.rpm_limit,
        tpm_limit=record.tpm_limit,
        concurrency_limit=record.concurrency_limit,
        budget_usd=record.budget_usd,
    )


def require_admin(request: Request) -> None:
    expected = request.app.state.services.settings.admin_token_value
    if not expected:
        raise GatewayError("invalid_api_key", "administração não configurada")
    token = _bearer(request) or request.headers.get("x-admin-token")
    if token is None:
        raise GatewayError("invalid_api_key", "credencial de administração em falta")
    if hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        return
    if looks_like_virtual_key(token):
        raise GatewayError("forbidden", "uma chave de inferência não acede à administração")
    raise GatewayError("invalid_api_key", "credencial de administração inválida")


async def team_exists(session, team_id: str) -> bool:  # noqa: ANN001 - AsyncSession
    result = await session.execute(select(Team.id).where(Team.id == team_id))
    return result.scalar_one_or_none() is not None
