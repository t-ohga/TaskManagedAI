"""SP-PHASE0 S4 DB-gated harness (mirrors tests/db/test_secret_constraints.py exactly).

``TASKMANAGEDAI_RUN_DB_TESTS=1`` + test PostgreSQL でのみ実行 (host dev では skip)。session_factory /
_run_alembic_upgrade / skip gate は既存 secret DB test と同一 pattern。LocalSecretStore は file mode を
強制 (``TASKHUB_DISABLE_KEYRING`` + per-test tmp base_dir) し、CI / 各環境で決定的に動かす。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-sp-phase0-s4-tests",
        ),
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("TASKMANAGEDAI_DATABASE_URL", None)
        else:
            os.environ["TASKMANAGEDAI_DATABASE_URL"] = previous
        get_settings.cache_clear()


async def assert_database_available(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("SP-PHASE0 S4 DB-gated tests require a reachable test database.") from exc
        import pytest

        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = integration_settings()
    await assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)

    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def reset_secret_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              secret_capability_tokens,
              secret_refs,
              notification_events,
              audit_events,
              ticket_relations,
              acceptance_criteria,
              tickets,
              repositories,
              projects,
              workspaces,
              principals,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def insert_tenant(session: AsyncSession, tenant_id: int, name: str) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (:tenant_id, :name, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"tenant_id": tenant_id, "name": name},
    )


async def insert_actor(
    session: AsyncSession,
    *,
    tenant_id: int,
    actor_id: UUID,
    stable_actor_id: str,
) -> None:
    await session.execute(
        text(
            """
            insert into actors (
              id, tenant_id, actor_type, actor_id, display_name, auth_context_hash, metadata
            )
            values (
              :actor_uuid, :tenant_id, 'human', :stable_actor_id,
              'SP-PHASE0 S4 Actor', :auth_hash, '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "actor_uuid": actor_id,
            "tenant_id": tenant_id,
            "stable_actor_id": stable_actor_id,
            # auth_context_hash は tenant-unique 制約に当たり得るため actor 毎に一意化。
            "auth_hash": f"sp-phase0-s4-{tenant_id}-{actor_id}",
        },
    )


async def fetch_secret_ref_row(
    session: AsyncSession, tenant_id: int, secret_ref_id: UUID
) -> dict[str, object] | None:
    result = await session.execute(
        text(
            """
            select status, material_state, material_purged_at, purge_attempts
            from secret_refs
            where tenant_id = :tenant_id and id = :id
            """
        ),
        {"tenant_id": tenant_id, "id": secret_ref_id},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


__all__ = [
    "assert_database_available",
    "fetch_secret_ref_row",
    "insert_actor",
    "insert_tenant",
    "integration_settings",
    "reset_secret_tables",
    "session_factory",
]
