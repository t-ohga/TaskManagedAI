"""SP-020 T04 memory insight aggregation contract tests."""

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
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.schemas.memory import MemoryInsightRequest, MemoryStoreRequest
from backend.app.services.memory.insights import (
    MemoryInsightDenied,
    MemoryInsightService,
)
from backend.app.services.memory.store import MemoryStoreService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000020401")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000020402")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000020403")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000020404")
RUN_ID = UUID("00000000-0000-4000-8000-000000020410")
OTHER_RUN_ID = UUID("00000000-0000-4000-8000-000000020411")
GENERATED_AT = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)

db_required = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _future_retention() -> datetime:
    return GENERATED_AT + timedelta(days=30)


def _insight_request(**overrides: object) -> MemoryInsightRequest:
    values: dict[str, object] = {
        "project_id": PROJECT_ID,
        "limit": 20,
    }
    values.update(overrides)
    return MemoryInsightRequest.model_validate(values)


def _store_request(**overrides: object) -> MemoryStoreRequest:
    values: dict[str, object] = {
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
        "record_kind": "auto_completion",
        "payload": {"body": "raw memory insight body must not leave artifact storage"},
        "classification": {"external_origin": True},
        "retention_until": _future_retention(),
    }
    values.update(overrides)
    return MemoryStoreRequest.model_validate(values)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-memory-insights",
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
            raise AssertionError("memory insight tests require PostgreSQL.") from exc
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
            values (:actor_id, 1, 'human', 'human:memory-insights',
                    'Memory Insights Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'memory-insights-workspace',
                    'memory-insights-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:project_id, 1, :workspace_id, 'memory-insights-project',
               'memory-insights-project', 'active', '{"rls_ready": true}'::jsonb),
              (:other_project_id, 1, :workspace_id, 'memory-insights-other-project',
               'memory-insights-other-project', 'active', '{"rls_ready": true}'::jsonb)
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
        {"config_hash": "a" * 64, "ruleset_hash": "b" * 64},
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
            "created_at": GENERATED_AT - timedelta(days=days_old),
            "retention_until": _future_retention(),
            "tenant_id": TENANT_ID,
            "record_id": record_id,
        },
    )


@pytest.mark.asyncio
@db_required
async def test_insights_are_ref_only_and_exclude_archived_or_expired_records(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            recent = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(record_kind="auto_completion"),
            )
            older_same_kind = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(
                    record_kind="auto_completion",
                    payload={"body": "older same kind raw body"},
                ),
            )
            archived = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(
                    record_kind="auto_failure",
                    payload={"body": "archived raw body"},
                ),
            )
            expired = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(
                    record_kind="auto_review_finding",
                    payload={"body": "expired raw body"},
                ),
            )
            await _age_record(session, record_id=recent.record.id, days_old=1)
            await _age_record(session, record_id=older_same_kind.record.id, days_old=4)
            await _age_record(session, record_id=archived.record.id, days_old=2)
            await _age_record(session, record_id=expired.record.id, days_old=3)
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
                    "archived_at": GENERATED_AT - timedelta(hours=1),
                    "tenant_id": TENANT_ID,
                    "record_id": archived.record.id,
                },
            )
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
                    "created_at": GENERATED_AT - timedelta(days=3),
                    "retention_until": GENERATED_AT - timedelta(days=1),
                    "tenant_id": TENANT_ID,
                    "record_id": expired.record.id,
                },
            )
            session.expire_all()
            result = await MemoryInsightService(session).summarize(
                tenant_id=TENANT_ID,
                request=_insight_request(),
                generated_at=GENERATED_AT,
            )

    assert [item.memory_record_id for item in result.items] == [
        recent.record.id,
        older_same_kind.record.id,
    ]
    assert {item.aggregate_count for item in result.items} == {2}
    assert result.items[0].score > result.items[1].score
    assert result.items[0].content_hash == recent.record.content_hash
    assert result.items[0].source_artifact_ref == (
        f"artifact://source/{recent.record.source_artifact_id}"
    )
    assert result.trust_level == "untrusted_content"
    serialized = str(result)
    assert "raw memory insight body" not in serialized
    assert "older same kind raw body" not in serialized
    assert "archived raw body" not in serialized
    assert "expired raw body" not in serialized


@pytest.mark.asyncio
@db_required
async def test_insights_support_record_kind_filter_and_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            completion = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(record_kind="auto_completion"),
            )
            failure = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(record_kind="auto_failure"),
            )
            await _age_record(session, record_id=completion.record.id, days_old=1)
            await _age_record(session, record_id=failure.record.id, days_old=1)
            session.expire_all()
            result = await MemoryInsightService(session).summarize(
                tenant_id=TENANT_ID,
                request=_insight_request(record_kinds=("auto_failure",), limit=1),
                generated_at=GENERATED_AT,
            )

    assert [item.memory_record_id for item in result.items] == [failure.record.id]
    assert result.items[0].record_kind == "auto_failure"
    assert result.items[0].aggregate_count == 1


@pytest.mark.asyncio
@db_required
async def test_insights_reject_project_boundary_and_naive_time(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            with pytest.raises(MemoryInsightDenied, match="project_id"):
                await MemoryInsightService(session).summarize(
                    tenant_id=TENANT_ID,
                    request=_insight_request(project_id=uuid4()),
                    generated_at=GENERATED_AT,
                )
            with pytest.raises(MemoryInsightDenied, match="timezone-aware"):
                await MemoryInsightService(session).summarize(
                    tenant_id=TENANT_ID,
                    request=_insight_request(),
                    generated_at=datetime(2026, 5, 24, 12, 0),
                )
