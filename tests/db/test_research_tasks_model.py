from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.research_task import ResearchTask
from backend.app.db.session import create_engine

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000010001")
TENANT_2_ACTOR_ID = UUID("00000000-0000-4000-8000-000000010002")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000010003")
TENANT_2_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000010004")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000010005")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000010006")
TENANT_2_PROJECT_ID = UUID("00000000-0000-4000-8000-000000010007")
RESEARCH_TASK_ID = UUID("00000000-0000-4000-8000-000000010008")
RESEARCH_TASK_DEFAULT_TENANT_ID = UUID("00000000-0000-4000-8000-000000010009")
RESEARCH_TASK_BAD_STATUS_ID = UUID("00000000-0000-4000-8000-000000010010")
RESEARCH_TASK_EMPTY_TITLE_ID = UUID("00000000-0000-4000-8000-000000010011")
RESEARCH_TASK_LONG_DESCRIPTION_ID = UUID("00000000-0000-4000-8000-000000010012")
RESEARCH_TASK_CROSS_TENANT_ID = UUID("00000000-0000-4000-8000-000000010013")

ForeignKeySignature = tuple[str, tuple[str, ...], str, tuple[str, ...]]


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-research-task-tests",
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
            raise AssertionError("Research task model tests require a reachable test database.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)

    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

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

        if current.__cause__ is not None:
            queue.append(current.__cause__)
        if current.__context__ is not None:
            queue.append(current.__context__)
        for arg in getattr(current, "args", ()):
            if isinstance(arg, BaseException):
                queue.append(arg)

    return None


def _assert_integrity_error(
    error: IntegrityError,
    *,
    sqlstate: str,
    constraint_name: str,
) -> None:
    assert _sqlstate(error) == sqlstate
    actual_constraint_name = (
        getattr(error.orig, "constraint_name", None)
        or getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)
    )
    assert actual_constraint_name == constraint_name


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate evidence_sources, research_tasks, projects, workspaces, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_two_tenant_project_fixtures(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values
              (1, 'tenant-one', '{"rls_ready": true}'::jsonb),
              (2, 'tenant-two', '{"rls_ready": true}'::jsonb)
            """
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values
              (:actor_id, 1, 'human', 'human:research', 'Research Actor',
                '{"rls_ready": true}'::jsonb),
              (:tenant_2_actor_id, 2, 'human', 'human:research', 'Tenant 2 Research Actor',
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID, "tenant_2_actor_id": TENANT_2_ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values
              (:workspace_id, 1, 'workspace', 'workspace', :actor_id,
                '{"rls_ready": true}'::jsonb),
              (:tenant_2_workspace_id, 2, 'workspace', 'workspace', :tenant_2_actor_id,
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "workspace_id": WORKSPACE_ID,
            "actor_id": ACTOR_ID,
            "tenant_2_workspace_id": TENANT_2_WORKSPACE_ID,
            "tenant_2_actor_id": TENANT_2_ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:project_a_id, 1, :workspace_id, 'project-a', 'project-a', 'active',
                '{"rls_ready": true}'::jsonb),
              (:project_b_id, 1, :workspace_id, 'project-b', 'project-b', 'active',
                '{"rls_ready": true}'::jsonb),
              (:tenant_2_project_id, 2, :tenant_2_workspace_id, 'project-a', 'project-a',
                'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "workspace_id": WORKSPACE_ID,
            "tenant_2_project_id": TENANT_2_PROJECT_ID,
            "tenant_2_workspace_id": TENANT_2_WORKSPACE_ID,
        },
    )


async def _table_columns(
    session: AsyncSession,
    table_name: str,
    column_names: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    result = await session.execute(
        text(
            """
            select column_name, is_nullable, column_default, data_type
            from information_schema.columns
            where table_schema = 'public'
              and table_name = :table_name
              and column_name = any(:column_names)
            """
        ),
        {"table_name": table_name, "column_names": list(column_names)},
    )
    return {str(row["column_name"]): dict(row) for row in result.mappings()}


async def _constraint_columns(
    session: AsyncSession,
    *,
    table_name: str,
    constraint_name: str,
    constraint_type: str,
) -> tuple[str, ...]:
    result = await session.execute(
        text(
            """
            select array_agg(att.attname order by keys.ord) as constrained_columns
            from pg_constraint con
            join pg_class rel on rel.oid = con.conrelid
            join unnest(con.conkey) with ordinality as keys(attnum, ord) on true
            join pg_attribute att
              on att.attrelid = con.conrelid and att.attnum = keys.attnum
            where con.contype::text = :constraint_type
              and rel.relname = :table_name
              and con.conname = :constraint_name
            group by con.conname
            """
        ),
        {
            "constraint_type": constraint_type,
            "table_name": table_name,
            "constraint_name": constraint_name,
        },
    )
    columns = result.scalar_one_or_none()
    if columns is None:
        return ()
    return tuple(str(column) for column in columns)


async def _constraint_definition(
    session: AsyncSession,
    *,
    table_name: str,
    constraint_name: str,
) -> str:
    definition = await session.scalar(
        text(
            """
            select pg_get_constraintdef(con.oid)
            from pg_constraint con
            join pg_class rel on rel.oid = con.conrelid
            where rel.relname = :table_name
              and con.conname = :constraint_name
            """
        ),
        {"table_name": table_name, "constraint_name": constraint_name},
    )
    assert isinstance(definition, str)
    return definition


async def _foreign_key_signatures(
    session: AsyncSession,
    table_names: frozenset[str],
) -> set[ForeignKeySignature]:
    result = await session.execute(
        text(
            """
            select
              rel.relname as table_name,
              array_agg(att.attname order by keys.ord) as constrained_columns,
              refrel.relname as referenced_table,
              array_agg(refatt.attname order by keys.ord) as referred_columns
            from pg_constraint con
            join pg_class rel on rel.oid = con.conrelid
            join pg_class refrel on refrel.oid = con.confrelid
            join unnest(con.conkey, con.confkey) with ordinality
              as keys(attnum, refattnum, ord) on true
            join pg_attribute att
              on att.attrelid = con.conrelid and att.attnum = keys.attnum
            join pg_attribute refatt
              on refatt.attrelid = con.confrelid and refatt.attnum = keys.refattnum
            where con.contype = 'f'
              and rel.relname = any(:table_names)
            group by con.conname, rel.relname, refrel.relname
            order by rel.relname, con.conname
            """
        ),
        {"table_names": sorted(table_names)},
    )

    signatures: set[ForeignKeySignature] = set()
    for row in result.mappings():
        signatures.add(
            (
                str(row["table_name"]),
                tuple(str(column) for column in row["constrained_columns"]),
                str(row["referenced_table"]),
                tuple(str(column) for column in row["referred_columns"]),
            )
        )
    return signatures


def test_research_task_model_declares_expected_table_columns_and_types() -> None:
    table = ResearchTask.__table__

    assert table.name == "research_tasks"
    assert set(table.c.keys()) == {
        "id",
        "tenant_id",
        "project_id",
        "created_by_actor_id",
        "title",
        "description",
        "status",
        "metadata",
        "created_at",
        "updated_at",
    }

    assert isinstance(table.c.id.type, PG_UUID)
    assert isinstance(table.c.tenant_id.type, sa.BigInteger)
    assert isinstance(table.c.project_id.type, PG_UUID)
    assert isinstance(table.c.created_by_actor_id.type, PG_UUID)
    assert isinstance(table.c.title.type, sa.Text)
    assert isinstance(table.c.description.type, sa.Text)
    assert isinstance(table.c.status.type, sa.Text)
    assert isinstance(table.c["metadata"].type, JSONB)
    assert isinstance(table.c.created_at.type, sa.DateTime)
    assert table.c.created_at.type.timezone is True
    assert isinstance(table.c.updated_at.type, sa.DateTime)
    assert table.c.updated_at.type.timezone is True

    constraint_names = {constraint.name for constraint in table.constraints}
    assert "research_tasks_ck_status" in constraint_names
    assert "research_tasks_ck_title_length" in constraint_names
    assert "research_tasks_ck_description_length" in constraint_names
    assert "research_tasks_project_fkey" in constraint_names
    assert "research_tasks_created_by_actor_fkey" in constraint_names
    assert "research_tasks_uq_tenant_id" in constraint_names
    assert "research_tasks_uq_tenant_project_id" in constraint_names


@pytest.mark.asyncio
async def test_research_tasks_schema_columns_constraints_and_foreign_keys(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    column_names = (
        "id",
        "tenant_id",
        "project_id",
        "created_by_actor_id",
        "title",
        "description",
        "status",
        "metadata",
        "created_at",
        "updated_at",
    )

    async with session_factory() as session:
        columns = await _table_columns(session, "research_tasks", column_names)
        tenant_unique = await _constraint_columns(
            session,
            table_name="research_tasks",
            constraint_name="research_tasks_uq_tenant_id",
            constraint_type="u",
        )
        tenant_project_unique = await _constraint_columns(
            session,
            table_name="research_tasks",
            constraint_name="research_tasks_uq_tenant_project_id",
            constraint_type="u",
        )
        status_check = await _constraint_definition(
            session,
            table_name="research_tasks",
            constraint_name="research_tasks_ck_status",
        )
        title_check = await _constraint_definition(
            session,
            table_name="research_tasks",
            constraint_name="research_tasks_ck_title_length",
        )
        description_check = await _constraint_definition(
            session,
            table_name="research_tasks",
            constraint_name="research_tasks_ck_description_length",
        )
        foreign_keys = await _foreign_key_signatures(session, frozenset({"research_tasks"}))

    assert set(columns) == set(column_names)
    assert columns["id"]["data_type"] == "uuid"
    assert columns["id"]["is_nullable"] == "NO"
    assert "uuid_generate_v4" in str(columns["id"]["column_default"])
    assert columns["tenant_id"]["data_type"] == "bigint"
    assert columns["tenant_id"]["is_nullable"] == "NO"
    assert columns["tenant_id"]["column_default"] == "1"
    assert columns["project_id"]["data_type"] == "uuid"
    assert columns["project_id"]["is_nullable"] == "NO"
    assert columns["created_by_actor_id"]["data_type"] == "uuid"
    assert columns["created_by_actor_id"]["is_nullable"] == "NO"
    assert columns["title"]["data_type"] == "text"
    assert columns["title"]["is_nullable"] == "NO"
    assert columns["description"]["data_type"] == "text"
    assert columns["description"]["is_nullable"] == "YES"
    assert columns["status"]["data_type"] == "text"
    assert columns["status"]["is_nullable"] == "NO"
    assert columns["metadata"]["data_type"] == "jsonb"
    assert columns["metadata"]["is_nullable"] == "NO"
    assert "rls_ready" in str(columns["metadata"]["column_default"])
    assert columns["created_at"]["data_type"] == "timestamp with time zone"
    assert columns["created_at"]["is_nullable"] == "NO"
    assert columns["updated_at"]["data_type"] == "timestamp with time zone"
    assert columns["updated_at"]["is_nullable"] == "NO"

    assert tenant_unique == ("tenant_id", "id")
    assert tenant_project_unique == ("tenant_id", "project_id", "id")
    for status in ("queued", "running", "completed", "failed"):
        assert status in status_check
    assert "length(title)" in title_check
    assert "200" in title_check
    assert "description" in description_check
    assert "2000" in description_check

    assert {
        ("research_tasks", ("tenant_id",), "tenants", ("id",)),
        ("research_tasks", ("tenant_id", "project_id"), "projects", ("tenant_id", "id")),
        ("research_tasks", ("tenant_id", "created_by_actor_id"), "actors", ("tenant_id", "id")),
    } <= foreign_keys


@pytest.mark.asyncio
async def test_research_tasks_tenant_id_defaults_to_one(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_tenant_project_fixtures(session)

        result = await session.execute(
            text(
                """
                insert into research_tasks (
                  id, project_id, created_by_actor_id, title, status
                )
                values (
                  :task_id, :project_id, :actor_id, 'Default tenant task', 'queued'
                )
                returning tenant_id, metadata
                """
            ),
            {
                "task_id": RESEARCH_TASK_DEFAULT_TENANT_ID,
                "project_id": PROJECT_A_ID,
                "actor_id": ACTOR_ID,
            },
        )
        row = result.mappings().one()
        await session.commit()

    assert row["tenant_id"] == 1
    metadata = row["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["rls_ready"] is True


@pytest.mark.asyncio
async def test_research_tasks_status_check_rejects_unknown_value(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_tenant_project_fixtures(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into research_tasks (
                      id, tenant_id, project_id, created_by_actor_id, title, status, metadata
                    )
                    values (
                      :task_id, 1, :project_id, :actor_id, 'Bad Status', 'cancelled',
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "task_id": RESEARCH_TASK_BAD_STATUS_ID,
                    "project_id": PROJECT_A_ID,
                    "actor_id": ACTOR_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="research_tasks_ck_status",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_research_tasks_title_and_description_length_checks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_tenant_project_fixtures(session)
        await session.commit()

        with pytest.raises(IntegrityError) as empty_title_exc:
            await session.execute(
                text(
                    """
                    insert into research_tasks (
                      id, tenant_id, project_id, created_by_actor_id, title, description, status, metadata
                    )
                    values (
                      :task_id, 1, :project_id, :actor_id, '', null, 'queued',
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "task_id": RESEARCH_TASK_EMPTY_TITLE_ID,
                    "project_id": PROJECT_A_ID,
                    "actor_id": ACTOR_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            empty_title_exc.value,
            sqlstate="23514",
            constraint_name="research_tasks_ck_title_length",
        )
        await session.rollback()

        with pytest.raises(IntegrityError) as long_description_exc:
            await session.execute(
                text(
                    """
                    insert into research_tasks (
                      id, tenant_id, project_id, created_by_actor_id, title, description, status, metadata
                    )
                    values (
                      :task_id, 1, :project_id, :actor_id, 'Long Description',
                      :description, 'queued', '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "task_id": RESEARCH_TASK_LONG_DESCRIPTION_ID,
                    "project_id": PROJECT_A_ID,
                    "actor_id": ACTOR_ID,
                    "description": "x" * 2001,
                },
            )
            await session.commit()

        _assert_integrity_error(
            long_description_exc.value,
            sqlstate="23514",
            constraint_name="research_tasks_ck_description_length",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_research_tasks_cross_tenant_actor_insert_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_tenant_project_fixtures(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into research_tasks (
                      id, tenant_id, project_id, created_by_actor_id, title, status, metadata
                    )
                    values (
                      :task_id, 1, :project_id, :tenant_2_actor_id, 'Cross Tenant Actor',
                      'queued', '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "task_id": RESEARCH_TASK_CROSS_TENANT_ID,
                    "project_id": PROJECT_A_ID,
                    "tenant_2_actor_id": TENANT_2_ACTOR_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="research_tasks_created_by_actor_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_research_tasks_cross_tenant_project_insert_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """F-S10B0-R1-002 fix: AC-HARD-03 trace。
    tenant_id=1 + project_id=tenant_2_project の cross-tenant project INSERT は
    research_tasks_project_fkey (tenant_id + project_id 複合 FK) で reject される
    ことを runtime で固定する (introspection だけでなく実 IntegrityError を踏む)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_tenant_project_fixtures(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into research_tasks (
                      id, tenant_id, project_id, created_by_actor_id, title, status, metadata
                    )
                    values (
                      :task_id, 1, :tenant_2_project_id, :actor_id, 'Cross Tenant Project',
                      'queued', '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "task_id": RESEARCH_TASK_CROSS_TENANT_ID,
                    "tenant_2_project_id": TENANT_2_PROJECT_ID,
                    "actor_id": ACTOR_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="research_tasks_project_fkey",
        )
        await session.rollback()


# TODO BL-0029c: add cross-project child-reference negative fixture with claims/evidence_items in batch 1.
