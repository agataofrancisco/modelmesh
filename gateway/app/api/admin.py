"""Administração: equipas, chaves e políticas. Exige o token de admin (ver auth/dependencies.py)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from gateway.app.api.schemas import KeyCreate, TeamCreate
from gateway.app.auth.dependencies import require_admin
from gateway.app.auth.keys import generate_key
from gateway.app.errors import GatewayError
from gateway.app.policy.schemas import TeamPolicy
from gateway.app.store import repository
from gateway.app.store.models import ApiKey, Team

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _team_json(team: Team) -> dict[str, Any]:
    return {"id": team.id, "name": team.name, "created_at": _iso(team.created_at)}


def _key_json(key: ApiKey) -> dict[str, Any]:
    """Nunca inclui o hash nem a chave em claro (a chave só aparece na criação)."""
    return {
        "id": key.id,
        "team_id": key.team_id,
        "name": key.name,
        "prefix": key.prefix,
        "status": key.status,
        "rpm_limit": key.rpm_limit,
        "tpm_limit": key.tpm_limit,
        "concurrency_limit": key.concurrency_limit,
        "budget_usd": str(key.budget_usd) if key.budget_usd is not None else None,
        "created_at": _iso(key.created_at),
        "revoked_at": _iso(key.revoked_at),
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


@router.post("/teams", status_code=201)
async def create_team(request: Request, body: TeamCreate) -> dict[str, Any]:
    async with request.app.state.services.session_factory() as session:
        if await repository.get_team(session, body.id) is not None:
            raise GatewayError("conflict", "equipa já existe")
        try:
            team = await repository.create_team(session, body.id, body.name)
        except IntegrityError as exc:
            await session.rollback()
            raise GatewayError("conflict", "equipa já existe") from exc
        return _team_json(team)


@router.get("/teams")
async def list_teams(request: Request) -> dict[str, Any]:
    async with request.app.state.services.session_factory() as session:
        teams = await repository.list_teams(session)
        return {"data": [_team_json(t) for t in teams]}


@router.post("/keys", status_code=201)
async def create_key(request: Request, body: KeyCreate) -> JSONResponse:
    services = request.app.state.services
    async with services.session_factory() as session:
        if await repository.get_team(session, body.team_id) is None:
            raise GatewayError("not_found", "equipa inexistente")
        issued = generate_key()
        row = await repository.create_key(
            session,
            body.team_id,
            body.name,
            issued,
            rpm_limit=body.rpm_limit,
            tpm_limit=body.tpm_limit,
            concurrency_limit=body.concurrency_limit,
            budget_usd=body.budget_usd,
        )
        payload = _key_json(row)
    payload["key"] = issued.plaintext  # mostrada uma única vez
    return JSONResponse(payload, status_code=201, headers={"cache-control": "no-store"})


@router.get("/keys")
async def list_keys(request: Request, team: str | None = None) -> dict[str, Any]:
    async with request.app.state.services.session_factory() as session:
        rows = await repository.list_keys(session, team)
        return {"data": [_key_json(k) for k in rows]}


@router.post("/keys/{key_id}/revoke")
async def revoke_key(request: Request, key_id: str) -> dict[str, Any]:
    async with request.app.state.services.session_factory() as session:
        row = await repository.revoke_key(session, key_id)
        if row is None:
            raise GatewayError("not_found", "chave inexistente")
        return _key_json(row)


@router.get("/policies/{team}")
async def get_policy(request: Request, team: str) -> dict[str, Any]:
    async with request.app.state.services.session_factory() as session:
        row = await repository.latest_policy(session, team)
        if row is None:
            raise GatewayError("not_found", "equipa sem política")
        return {"team_id": team, "version": row.version, "policy": row.body}


@router.put("/policies/{team}")
async def put_policy(request: Request, team: str, body: TeamPolicy) -> dict[str, Any]:
    services = request.app.state.services
    unknown = sorted(body.provider_refs() - set(services.settings.providers))
    if unknown:
        # A política anterior mantém-se: nada é escrito quando a validação falha.
        raise GatewayError(
            "validation_error",
            "a política referencia providers inexistentes",
            details={"unknown_providers": unknown},
        )
    async with services.session_factory() as session:
        if await repository.get_team(session, team) is None:
            raise GatewayError("not_found", "equipa inexistente")
        row = await repository.append_policy(session, team, body.model_dump(mode="json"))
        return {"team_id": team, "version": row.version, "policy": row.body}
