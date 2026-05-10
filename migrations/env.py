from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, pool

from backend.app.config import get_settings
from backend.app.db.session import create_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None
# Alembic default alembic_version.version_num is varchar(32) (hard limit).
# Project convention recommends <= 30 chars for 2-char safety margin.
MAX_REVISION_ID_LENGTH = 32


def get_database_url() -> str:
    return get_settings().database_url


def assert_revision_ids_within_limit() -> None:
    script = ScriptDirectory.from_config(config)
    too_long = sorted(
        revision.revision
        for revision in script.walk_revisions()
        if len(revision.revision) > MAX_REVISION_ID_LENGTH
    )
    if too_long:
        details = ", ".join(f"{revision} ({len(revision)} chars)" for revision in too_long)
        raise RuntimeError(
            "Alembic revision_id must be <= "
            f"{MAX_REVISION_ID_LENGTH} chars to fit alembic_version.version_num: {details}"
        )


def run_migrations_offline() -> None:
    assert_revision_ids_within_limit()
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_engine(get_database_url())

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    assert_revision_ids_within_limit()
    config.set_main_option("sqlalchemy.url", get_database_url())
    config.attributes["poolclass"] = pool.NullPool
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

