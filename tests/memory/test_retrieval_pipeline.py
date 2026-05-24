"""SP-018 T05 memory retrieval pipeline contract tests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.schemas.memory import MemoryRetrievalRequest, MemoryStoreRequest
from backend.app.services.memory.retrieval import (
    MemoryRetrievalDenied,
    MemoryRetrievalService,
)
from backend.app.services.memory.store import MemoryStoreService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000018201")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000018202")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000018203")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000018204")
RUN_ID = UUID("00000000-0000-4000-8000-000000018210")
OTHER_RUN_ID = UUID("00000000-0000-4000-8000-000000018211")

db_required = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _future_retention() -> datetime:
    return datetime.now(tz=UTC) + timedelta(days=30)


def _store_request(**overrides: object) -> MemoryStoreRequest:
    values: dict[str, object] = {
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
        "record_kind": "manual_user",
        "payload": {"body": "raw memory content must stay behind artifact ref"},
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
        dev_login_cookie_secret="test-cookie-secret-memory-retrieval",
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
            raise AssertionError("memory retrieval tests require PostgreSQL.") from exc
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
            values (:actor_id, 1, 'human', 'human:memory-retrieval',
                    'Memory Retrieval Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'memory-retrieval-workspace',
                    'memory-retrieval-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:project_id, 1, :workspace_id, 'memory-retrieval-project',
               'memory-retrieval-project', 'active', '{"rls_ready": true}'::jsonb),
              (:other_project_id, 1, :workspace_id, 'memory-retrieval-other-project',
               'memory-retrieval-other-project', 'active', '{"rls_ready": true}'::jsonb)
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
        {"config_hash": "4" * 64, "ruleset_hash": "5" * 64},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, status)
            values
              (:run_id, 1, :project_id, 'running'),
              (:other_run_id, 1, :other_project_id, 'running')
            """
        ),
        {
            "run_id": RUN_ID,
            "project_id": PROJECT_ID,
            "other_run_id": OTHER_RUN_ID,
            "other_project_id": OTHER_PROJECT_ID,
        },
    )


def test_memory_retrieval_request_removes_server_owned_fields() -> None:
    MemoryRetrievalRequest.model_validate(
        {"project_id": PROJECT_ID, "retrieval_run_id": RUN_ID}
    )

    for server_owned_field in (
        "retrieval_artifact_ref",
        "retrieval_hash",
        "sanitizer_version_id",
        "trust_level",
        "context_snapshot_id",
    ):
        with pytest.raises(ValidationError, match=f"extra_forbidden|{server_owned_field}"):
            MemoryRetrievalRequest.model_validate(
                {
                    "project_id": PROJECT_ID,
                    "retrieval_run_id": RUN_ID,
                    server_owned_field: "caller-owned",
                }
            )


@pytest.mark.asyncio
@db_required
async def test_retrieve_creates_ref_only_untrusted_retrieval_artifact(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            stored = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(),
            )
            result = await MemoryRetrievalService(session).retrieve(
                tenant_id=TENANT_ID,
                request=_retrieval_request(memory_record_ids=(stored.record.id,)),
            )

    assert [record.id for record in result.records] == [stored.record.id]
    assert result.artifact is not None
    assert result.artifact.exportable is False
    assert result.artifact.content_hash == result.retrieval_hash
    assert result.artifact.content_jsonb["trust_level"] == "untrusted_content"
    assert result.artifact.content_jsonb["records"] == [
        {
            "content_artifact_ref": stored.record.content_artifact_ref,
            "content_hash": stored.record.content_hash,
            "data_class": "internal",
            "memory_record_id": str(stored.record.id),
            "record_kind": "manual_user",
            "redaction_status": "redacted",
            "sanitizer_version_id": str(stored.record.sanitizer_version_id),
            "trust_level": "untrusted_content",
        }
    ]
    assert "raw memory content" not in str(result.artifact.content_jsonb)
    assert len(result.retrieval_artifacts) == 1
    retrieval_row = result.retrieval_artifacts[0]
    assert retrieval_row.memory_record_id == stored.record.id
    assert retrieval_row.retrieval_artifact_ref == (
        f"artifact://memory-retrieval/{result.artifact.id}"
    )
    assert retrieval_row.retrieval_hash == result.retrieval_hash
    assert retrieval_row.retrieval_run_id == RUN_ID
    assert retrieval_row.trust_level == "untrusted_content"
    assert result.payload_data_class == "internal"
    assert result.sanitizer_policy_version == "v1.0.0"


@pytest.mark.asyncio
@db_required
async def test_retrieve_denies_explicit_cross_project_record_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            stored = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(),
            )
            with pytest.raises(MemoryRetrievalDenied, match="memory_record_not_found"):
                await MemoryRetrievalService(session).retrieve(
                    tenant_id=TENANT_ID,
                    request=_retrieval_request(
                        project_id=OTHER_PROJECT_ID,
                        retrieval_run_id=OTHER_RUN_ID,
                        memory_record_ids=(stored.record.id,),
                    ),
                )

        retrieval_count = await session.scalar(
            text("select count(*) from memory_retrieval_artifacts")
        )

    assert retrieval_count == 0


@pytest.mark.asyncio
@db_required
async def test_retrieve_excludes_archived_and_expired_records(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            archived = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(payload={"body": "archived content"}),
            )
            expired = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(payload={"body": "expired content"}),
            )
            await session.execute(
                text(
                    """
                    update memory_records
                       set archived_at = now()
                     where tenant_id = :tenant_id
                       and id = :record_id
                    """
                ),
                {"tenant_id": TENANT_ID, "record_id": archived.record.id},
            )
            await session.execute(
                text(
                    """
                    update memory_records
                       set created_at = now() - interval '10 days',
                           retention_until = now() - interval '1 day'
                     where tenant_id = :tenant_id
                       and id = :record_id
                    """
                ),
                {"tenant_id": TENANT_ID, "record_id": expired.record.id},
            )
            result = await MemoryRetrievalService(session).retrieve(
                tenant_id=TENANT_ID,
                request=_retrieval_request(),
            )

        retrieval_count = await session.scalar(
            text("select count(*) from memory_retrieval_artifacts")
        )

    assert result.records == ()
    assert result.artifact is None
    assert result.retrieval_artifacts == ()
    assert retrieval_count == 0
