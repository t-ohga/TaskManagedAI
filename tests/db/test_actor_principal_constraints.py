from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000000301")
DUPLICATE_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000304")
CROSS_TENANT_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000305")
PRINCIPAL_ID = UUID("00000000-0000-4000-8000-000000000302")
CROSS_TENANT_PRINCIPAL_ID = UUID("00000000-0000-4000-8000-000000000303")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-constraint-tests",
        ),
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous_database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()

    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        command.upgrade(config, "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("TASKMANAGEDAI_DATABASE_URL", None)
        else:
            os.environ["TASKMANAGEDAI_DATABASE_URL"] = previous_database_url
        get_settings.cache_clear()


async def _assert_database_available(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("Constraint tests require a reachable test database.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)

    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        yield factory
    finally:
        await engine.dispose()


def _sqlstate(error: BaseException) -> str | None:
    queue: list[BaseException] = [error]
    seen: set[int] = set()

    while queue:
        current = queue.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))

        state = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if isinstance(state, str):
            return state

        cause = current.__cause__
        if cause is not None:
            queue.append(cause)

        context = current.__context__
        if context is not None:
            queue.append(context)

        for arg in getattr(current, "args", ()):
            if isinstance(arg, BaseException):
                queue.append(arg)

    return None


async def _reset_core_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate repositories, projects, workspaces, principals, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_tenant(session: AsyncSession, tenant_id: int, name: str) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (:tenant_id, :name, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"tenant_id": tenant_id, "name": name},
    )


async def _insert_human_actor(
    session: AsyncSession,
    *,
    tenant_id: int,
    actor_id: UUID,
    stable_actor_id: str = "human:constraint-test",
) -> None:
    await session.execute(
        text(
            """
            insert into actors (
              id,
              tenant_id,
              actor_type,
              actor_id,
              display_name,
              auth_context_hash,
              metadata
            )
            values (
              :actor_uuid,
              :tenant_id,
              'human',
              :stable_actor_id,
              'Constraint Test Actor',
              'constraint-test-auth-context',
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "actor_uuid": actor_id,
            "tenant_id": tenant_id,
            "stable_actor_id": stable_actor_id,
        },
    )


@pytest.mark.asyncio
async def test_actors_actor_type_rejects_unknown_value(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_core_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into actors (
                      id,
                      tenant_id,
                      actor_type,
                      actor_id,
                      display_name,
                      auth_context_hash,
                      metadata
                    )
                    values (
                      :actor_uuid,
                      1,
                      'robot',
                      'robot:bad',
                      'Bad Actor',
                      'bad-actor-context',
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"actor_uuid": ACTOR_ID},
            )
            await session.commit()

        assert _sqlstate(exc_info.value) == "23514"
        await session.rollback()


@pytest.mark.asyncio
async def test_actors_actor_id_is_unique_within_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_core_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_human_actor(
            session,
            tenant_id=1,
            actor_id=ACTOR_ID,
            stable_actor_id="human:default",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_human_actor(
                session,
                tenant_id=1,
                actor_id=DUPLICATE_ACTOR_ID,
                stable_actor_id="human:default",
            )
            await session.commit()

        assert _sqlstate(exc_info.value) == "23505"
        await session.rollback()


@pytest.mark.asyncio
async def test_actors_actor_id_can_repeat_across_tenants(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_core_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_tenant(session, 2, "tenant-two")
        await _insert_human_actor(
            session,
            tenant_id=1,
            actor_id=ACTOR_ID,
            stable_actor_id="human:default",
        )
        await _insert_human_actor(
            session,
            tenant_id=2,
            actor_id=CROSS_TENANT_ACTOR_ID,
            stable_actor_id="human:default",
        )
        await session.commit()

        actor_count = await session.scalar(
            text("select count(*) from actors where actor_id = 'human:default'")
        )

    assert actor_count == 2


@pytest.mark.asyncio
async def test_principals_principal_type_rejects_unknown_value(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_core_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_human_actor(session, tenant_id=1, actor_id=ACTOR_ID)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into principals (
                      id,
                      tenant_id,
                      actor_id,
                      principal_type,
                      auth_context_hash,
                      metadata
                    )
                    values (
                      :principal_id,
                      1,
                      :actor_id,
                      'password',
                      'bad-principal-context',
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"principal_id": PRINCIPAL_ID, "actor_id": ACTOR_ID},
            )
            await session.commit()

        assert _sqlstate(exc_info.value) == "23514"
        await session.rollback()


@pytest.mark.asyncio
async def test_principal_actor_composite_fk_rejects_cross_tenant_actor(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_core_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_tenant(session, 2, "tenant-two")
        await _insert_human_actor(session, tenant_id=1, actor_id=ACTOR_ID)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into principals (
                      id,
                      tenant_id,
                      actor_id,
                      principal_type,
                      auth_context_hash,
                      metadata
                    )
                    values (
                      :principal_id,
                      2,
                      :actor_id,
                      'session',
                      'cross-tenant-context',
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "principal_id": CROSS_TENANT_PRINCIPAL_ID,
                    "actor_id": ACTOR_ID,
                },
            )
            await session.commit()

        assert _sqlstate(exc_info.value) == "23503"
        await session.rollback()

