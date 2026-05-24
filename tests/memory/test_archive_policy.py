"""SP-020 T03 memory archive policy contract tests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.models.memory_record import MemoryRecord
from backend.app.db.session import create_engine
from backend.app.schemas.memory import (
    MemoryArchivePolicyRequest,
    MemoryRetrievalRequest,
    MemoryStoreRequest,
)
from backend.app.services.memory.archive_policy import (
    MEMORY_ARCHIVE_ENGAGED_EVENT_TYPE,
    MemoryArchivePolicyError,
    MemoryArchivePolicyService,
)
from backend.app.services.memory.retrieval import MemoryRetrievalService
from backend.app.services.memory.store import MemoryStoreService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000020301")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000020302")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000020303")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000020304")
RUN_ID = UUID("00000000-0000-4000-8000-000000020310")
OTHER_RUN_ID = UUID("00000000-0000-4000-8000-000000020311")
EVALUATED_AT = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)

db_required = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _future_retention() -> datetime:
    return EVALUATED_AT + timedelta(days=30)


def _archive_request(**overrides: object) -> MemoryArchivePolicyRequest:
    values: dict[str, object] = {
        "project_id": PROJECT_ID,
        "minimum_age_days": 30,
        "max_records": 100,
    }
    values.update(overrides)
    return MemoryArchivePolicyRequest.model_validate(values)


def _store_request(**overrides: object) -> MemoryStoreRequest:
    values: dict[str, object] = {
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
        "record_kind": "auto_completion",
        "payload": {"body": "raw memory archive candidate body must not enter audit"},
        "classification": {"external_origin": True},
        "retention_until": _future_retention(),
    }
    values.update(overrides)
    return MemoryStoreRequest.model_validate(values)


def _retrieval_request(**overrides: object) -> MemoryRetrievalRequest:
    values: dict[str, object] = {
        "project_id": PROJECT_ID,
        "retrieval_run_id": RUN_ID,
        "limit": 20,
    }
    values.update(overrides)
    return MemoryRetrievalRequest.model_validate(values)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-memory-archive-policy",
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous_database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(_REPO_ROOT / "alembic.ini")), "head")
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
            raise AssertionError("memory archive policy tests require PostgreSQL.") from exc
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


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              memory_retrieval_artifacts,
              memory_records,
              audit_events,
              context_snapshots,
              artifacts,
              agent_run_events,
              agent_runs,
              sanitizer_policy_versions,
              projects,
              workspaces,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _insert_fixture(session: AsyncSession) -> None:
    await _reset_tables(session)
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            """
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:actor_id, 1, 'human', 'human:memory-archive',
                    'Memory Archive Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'memory-archive-workspace',
                    'memory-archive-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:project_id, 1, :workspace_id, 'memory-archive-project',
               'memory-archive-project', 'active', '{"rls_ready": true}'::jsonb),
              (:other_project_id, 1, :workspace_id, 'memory-archive-other-project',
               'memory-archive-other-project', 'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "project_id": PROJECT_ID,
            "other_project_id": OTHER_PROJECT_ID,
            "workspace_id": WORKSPACE_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into sanitizer_policy_versions (
              tenant_id, version, config_hash, ruleset_hash
            )
            values (1, 'v1.0.0', :config_hash, :ruleset_hash)
            """
        ),
        {"config_hash": "8" * 64, "ruleset_hash": "9" * 64},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, status)
            values
              (:run_id, 1, :project_id, 'completed'),
              (:other_run_id, 1, :other_project_id, 'completed')
            """
        ),
        {
            "run_id": RUN_ID,
            "project_id": PROJECT_ID,
            "other_run_id": OTHER_RUN_ID,
            "other_project_id": OTHER_PROJECT_ID,
        },
    )


async def _age_record(
    session: AsyncSession,
    *,
    record_id: UUID,
    days_old: int,
) -> None:
    created_at = EVALUATED_AT - timedelta(days=days_old)
    await session.execute(
        text(
            """
            update memory_records
               set created_at = :created_at,
                   retention_until = :retention_until
             where tenant_id = :tenant_id
               and id = :record_id
            """
        ),
        {
            "created_at": created_at,
            "retention_until": _future_retention(),
            "tenant_id": TENANT_ID,
            "record_id": record_id,
        },
    )


def test_archive_policy_request_protects_manual_user_by_schema() -> None:
    _archive_request()
    with pytest.raises(ValidationError):
        _archive_request(record_kinds=("manual_user",))
    with pytest.raises(ValidationError, match="unique"):
        _archive_request(record_kinds=("auto_completion", "auto_completion"))


@pytest.mark.asyncio
@db_required
async def test_archive_policy_archives_auto_records_and_keeps_manual_user_retrievable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            auto_record = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(record_kind="auto_completion"),
            )
            manual_record = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(
                    record_kind="manual_user",
                    payload={"body": "manual user memory must stay active"},
                ),
            )
            await _age_record(session, record_id=auto_record.record.id, days_old=45)
            await _age_record(session, record_id=manual_record.record.id, days_old=45)
            result = await MemoryArchivePolicyService(session).archive_low_value(
                tenant_id=TENANT_ID,
                request=_archive_request(),
                evaluated_at=EVALUATED_AT,
            )
            retrieval = await MemoryRetrievalService(session).retrieve(
                tenant_id=TENANT_ID,
                request=_retrieval_request(),
            )

        auto_after = await session.scalar(
            select(MemoryRecord).where(MemoryRecord.id == auto_record.record.id)
        )
        manual_after = await session.scalar(
            select(MemoryRecord).where(MemoryRecord.id == manual_record.record.id)
        )
        audit_event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == MEMORY_ARCHIVE_ENGAGED_EVENT_TYPE
            )
        )

    assert [record.id for record in result.archived_records] == [auto_record.record.id]
    assert auto_after is not None
    assert auto_after.archived_at == EVALUATED_AT
    assert manual_after is not None
    assert manual_after.archived_at is None
    assert [record.id for record in retrieval.records] == [manual_record.record.id]
    assert result.audit_event is not None
    assert audit_event is not None
    assert audit_event.event_payload["archived_count"] == 1
    assert audit_event.event_payload["policy"]["manual_user_protected"] is True
    assert audit_event.event_payload["policy"]["hard_delete"] is False
    assert "raw memory archive candidate body" not in str(audit_event.event_payload)
    assert "manual user memory must stay active" not in str(audit_event.event_payload)


@pytest.mark.asyncio
@db_required
async def test_archive_policy_skips_young_expired_and_already_archived_records(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            young = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(payload={"body": "young memory"}),
            )
            expired = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(payload={"body": "expired memory"}),
            )
            already_archived = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(payload={"body": "already archived memory"}),
            )
            await _age_record(session, record_id=young.record.id, days_old=5)
            await _age_record(session, record_id=expired.record.id, days_old=45)
            await _age_record(session, record_id=already_archived.record.id, days_old=45)
            await session.execute(
                text(
                    """
                    update memory_records
                       set created_at = :created_at,
                           retention_until = :retention_until
                     where tenant_id = :tenant_id
                       and id = :record_id
                    """
                ),
                {
                    "created_at": EVALUATED_AT - timedelta(days=45),
                    "retention_until": EVALUATED_AT - timedelta(days=1),
                    "tenant_id": TENANT_ID,
                    "record_id": expired.record.id,
                },
            )
            await session.execute(
                text(
                    """
                    update memory_records
                       set archived_at = :archived_at
                     where tenant_id = :tenant_id
                       and id = :record_id
                    """
                ),
                {
                    "archived_at": EVALUATED_AT - timedelta(days=1),
                    "tenant_id": TENANT_ID,
                    "record_id": already_archived.record.id,
                },
            )
            result = await MemoryArchivePolicyService(session).archive_low_value(
                tenant_id=TENANT_ID,
                request=_archive_request(),
                evaluated_at=EVALUATED_AT,
            )

        audit_count = await session.scalar(
            text(
                "select count(*) from audit_events where event_type = "
                "'memory_archive_engaged'"
            )
        )

    assert result.archived_records == ()
    assert result.audit_event is None
    assert audit_count == 0


@pytest.mark.asyncio
@db_required
async def test_archive_policy_rejects_cross_project_boundary_and_naive_time(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            with pytest.raises(MemoryArchivePolicyError, match="project_id"):
                await MemoryArchivePolicyService(session).archive_low_value(
                    tenant_id=TENANT_ID,
                    request=_archive_request(project_id=uuid4()),
                    evaluated_at=EVALUATED_AT,
                )
            with pytest.raises(MemoryArchivePolicyError, match="timezone-aware"):
                await MemoryArchivePolicyService(session).archive_low_value(
                    tenant_id=TENANT_ID,
                    request=_archive_request(),
                    evaluated_at=datetime(2026, 5, 24, 12, 0),
                )

        archive_count = await session.scalar(
            text("select count(*) from memory_records where archived_at is not null")
        )

    assert archive_count == 0
