"""Ambiente do Alembic. Usa URL síncrona derivada de MODELMESH_DATABASE_URL."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

from gateway.app.store.models import Base

config = context.config
target_metadata = Base.metadata


def _sync_url() -> str:
    url = os.environ.get("MODELMESH_DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    # Drivers assíncronos -> equivalentes síncronos para as migrações.
    return url.replace("+aiosqlite", "").replace("+asyncpg", "")


def run_migrations_offline() -> None:
    context.configure(url=_sync_url(), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_sync_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
