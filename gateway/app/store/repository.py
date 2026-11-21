"""Acesso a dados (Postgres/SQLite via SQLAlchemy). Todas as funções recebem uma sessão."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.auth.keys import IssuedKey
from gateway.app.store.models import ApiKey, Policy, Price, Team, UsageRecord


@dataclass(frozen=True)
class KeyRecord:
    id: str
    team_id: str
    name: str
    prefix: str
    status: str
    rpm_limit: int | None
    tpm_limit: int | None
    concurrency_limit: int | None
    budget_usd: Decimal | None


def _key_record(row: ApiKey) -> KeyRecord:
    return KeyRecord(
        id=row.id,
        team_id=row.team_id,
        name=row.name,
        prefix=row.prefix,
        status=row.status,
        rpm_limit=row.rpm_limit,
        tpm_limit=row.tpm_limit,
        concurrency_limit=row.concurrency_limit,
        budget_usd=row.budget_usd,
    )


# ---------- equipas ----------
async def create_team(session: AsyncSession, team_id: str, name: str) -> Team:
    team = Team(id=team_id, name=name)
    session.add(team)
    await session.commit()
    return team


async def get_team(session: AsyncSession, team_id: str) -> Team | None:
    return await session.get(Team, team_id)


async def list_teams(session: AsyncSession) -> list[Team]:
    result = await session.execute(select(Team).order_by(Team.id))
    return list(result.scalars())


# ---------- chaves ----------
async def create_key(
    session: AsyncSession,
    team_id: str,
    name: str,
    issued: IssuedKey,
    *,
    rpm_limit: int | None = None,
    tpm_limit: int | None = None,
    concurrency_limit: int | None = None,
    budget_usd: Decimal | None = None,
) -> ApiKey:
    row = ApiKey(
        team_id=team_id,
        name=name,
        prefix=issued.prefix,
        key_hash=issued.key_hash,
        status="active",
        rpm_limit=rpm_limit,
        tpm_limit=tpm_limit,
        concurrency_limit=concurrency_limit,
        budget_usd=budget_usd,
    )
    session.add(row)
    await session.commit()
    return row


async def get_key_by_hash(session: AsyncSession, key_hash: str) -> KeyRecord | None:
    result = await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    row = result.scalar_one_or_none()
    return _key_record(row) if row else None


async def get_key(session: AsyncSession, key_id: str) -> ApiKey | None:
    return await session.get(ApiKey, key_id)


async def list_keys(session: AsyncSession, team_id: str | None = None) -> list[ApiKey]:
    stmt = select(ApiKey).order_by(ApiKey.created_at)
    if team_id:
        stmt = stmt.where(ApiKey.team_id == team_id)
    return list((await session.execute(stmt)).scalars())


async def revoke_key(session: AsyncSession, key_id: str) -> ApiKey | None:
    row = await session.get(ApiKey, key_id)
    if row is None:
        return None
    row.status = "revoked"
    row.revoked_at = datetime.now(UTC)
    await session.commit()
    return row


# ---------- políticas ----------
async def latest_policy(session: AsyncSession, team_id: str) -> Policy | None:
    stmt = select(Policy).where(Policy.team_id == team_id).order_by(Policy.version.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def all_latest_policy_bodies(session: AsyncSession) -> list[dict[str, Any]]:
    bodies: list[dict[str, Any]] = []
    for team in await list_teams(session):
        row = await latest_policy(session, team.id)
        if row is not None:
            bodies.append(row.body)
    return bodies


async def append_policy(session: AsyncSession, team_id: str, body: dict[str, Any]) -> Policy:
    current = await latest_policy(session, team_id)
    version = (current.version + 1) if current else 1
    row = Policy(team_id=team_id, version=version, body=body)
    session.add(row)
    await session.commit()
    return row


# ---------- preços ----------
async def list_prices(session: AsyncSession) -> list[Price]:
    return list((await session.execute(select(Price))).scalars())


async def upsert_price(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
    input_per_mtok: Decimal,
    output_per_mtok: Decimal,
    currency: str,
    effective_date: date,
    source: str,
) -> None:
    existing = (
        await session.execute(
            select(Price).where(
                Price.provider == provider,
                Price.model == model,
                Price.effective_date == effective_date,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Price(
                provider=provider,
                model=model,
                input_per_mtok=input_per_mtok,
                output_per_mtok=output_per_mtok,
                currency=currency,
                effective_date=effective_date,
                source=source,
            )
        )
    else:
        existing.input_per_mtok = input_per_mtok
        existing.output_per_mtok = output_per_mtok
        existing.currency = currency
        existing.source = source
    await session.commit()


# ---------- uso ----------
async def insert_usage(session: AsyncSession, record: dict[str, Any]) -> None:
    session.add(UsageRecord(**record))
    await session.commit()


async def usage_aggregate(
    session: AsyncSession,
    *,
    group_by: str,
    team_id: str | None = None,
    key_prefix: str | None = None,
    model: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    columns = {
        "team": UsageRecord.team_id,
        "key": UsageRecord.key_prefix,
        "model": UsageRecord.model_requested,
    }
    group_col = columns[group_by]
    stmt = select(
        group_col.label("group"),
        func.count(UsageRecord.id).label("requests"),
        func.coalesce(func.sum(UsageRecord.tokens_in), 0).label("tokens_in"),
        func.coalesce(func.sum(UsageRecord.tokens_out), 0).label("tokens_out"),
        func.coalesce(func.sum(UsageRecord.cost_real_usd), 0).label("cost_real_usd"),
        func.coalesce(func.sum(UsageRecord.cost_estimated_usd), 0).label("cost_estimated_usd"),
    ).group_by(group_col)
    if team_id:
        stmt = stmt.where(UsageRecord.team_id == team_id)
    if key_prefix:
        stmt = stmt.where(UsageRecord.key_prefix == key_prefix)
    if model:
        stmt = stmt.where(UsageRecord.model_requested == model)
    if since:
        stmt = stmt.where(UsageRecord.created_at >= since)
    if until:
        stmt = stmt.where(UsageRecord.created_at < until)
    rows = (await session.execute(stmt.order_by(group_col))).all()
    return [
        {
            "group": row.group,
            "requests": int(row.requests),
            "tokens_in": int(row.tokens_in),
            "tokens_out": int(row.tokens_out),
            "cost_real_usd": str(Decimal(row.cost_real_usd)),
            "cost_estimated_usd": str(Decimal(row.cost_estimated_usd)),
        }
        for row in rows
    ]


def default_usage_window(days: int = 7) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    return now - timedelta(days=days), now


async def spend_for_period(
    session: AsyncSession, *, team_id: str, key_id: str | None, period_start: datetime
) -> Decimal:
    """Soma do custo real persistido desde `period_start` (fonte para reconstruir Redis)."""
    stmt = select(func.coalesce(func.sum(UsageRecord.cost_real_usd), 0)).where(
        UsageRecord.team_id == team_id, UsageRecord.created_at >= period_start
    )
    if key_id is not None:
        stmt = stmt.where(UsageRecord.key_id == key_id)
    value = (await session.execute(stmt)).scalar_one()
    return Decimal(value)
