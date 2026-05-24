"""SP-018 T04 memory store pipeline contract tests."""

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
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.memory_record import MemoryRecord
from backend.app.db.session import create_engine
from backend.app.repositories.artifact import calculate_content_hash
from backend.app.schemas.memory import MemoryStoreRequest
from backend.app.services.memory.sanitizer import sanitize_memory_payload
from backend.app.services.memory.store import MemoryStoreError, MemoryStoreService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000018101")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000018102")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000018103")
RUN_ID = UUID("00000000-0000-4000-8000-000000018110")

db_required = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _future_retention() -> datetime:
    return datetime.now(tz=UTC) + timedelta(days=30)


def _request(**overrides: object) -> MemoryStoreRequest:
    values: dict[str, object] = {
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
        "record_kind": "manual_user",
        "payload": {"body": "remember the implementation decision"},
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
        dev_login_cookie_secret="test-cookie-secret-memory-store",
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
            raise AssertionError("memory store tests require PostgreSQL.") from exc
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
            values (:actor_id, 1, 'human', 'human:memory-store',
                    'Memory Store Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'memory-store-workspace',
                    'memory-store-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'memory-store-project',
                    'memory-store-project', 'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
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
        {"config_hash": "2" * 64, "ruleset_hash": "3" * 64},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, status)
            values (:run_id, 1, :project_id, 'running')
            """
        ),
        {"run_id": RUN_ID, "project_id": PROJECT_ID},
    )


def test_memory_store_request_removes_server_owned_fields() -> None:
    for server_owned_field in (
        "content_artifact_ref",
        "content_hash",
        "data_class",
        "redaction_status",
        "sanitizer_version_id",
        "source_artifact_id",
        "trust_level",
    ):
        with pytest.raises(ValidationError, match=f"extra_forbidden|{server_owned_field}"):
            MemoryStoreRequest.model_validate(
                {
                    "project_id": PROJECT_ID,
                    "run_id": RUN_ID,
                    "record_kind": "manual_user",
                    "payload": {"body": "hello"},
                    "retention_until": _future_retention(),
                    server_owned_field: "caller-owned",
                }
            )

    with pytest.raises(ValidationError, match="extra_forbidden|payload_data_class"):
        _request(classification={"payload_data_class": "pii"})


def test_memory_sanitizer_rejects_raw_secret_and_server_owned_claims() -> None:
    with pytest.raises(ValueError, match="prohibited key"):
        sanitize_memory_payload(
            {"secret": "redacted"},
            schema_version="memory-record.v1",
            sanitizer_policy_version="v1.0.0",
        )

    with pytest.raises(ValueError, match="raw secret pattern"):
        sanitize_memory_payload(
            {"body": "sk-" + "a" * 24},
            schema_version="memory-record.v1",
            sanitizer_policy_version="v1.0.0",
        )

    with pytest.raises(ValueError, match="server-owned claim key"):
        sanitize_memory_payload(
            {"trust_level": "validated_artifact"},
            schema_version="memory-record.v1",
            sanitizer_policy_version="v1.0.0",
        )


def test_memory_sanitizer_uses_canonical_artifact_hash() -> None:
    first = sanitize_memory_payload(
        {"decision": {"b": 2, "a": 1}},
        schema_version="memory-record.v1",
        sanitizer_policy_version="v1.0.0",
    )
    second = sanitize_memory_payload(
        {"decision": {"a": 1, "b": 2}},
        schema_version="memory-record.v1",
        sanitizer_policy_version="v1.0.0",
    )

    assert first.content_hash == second.content_hash
    assert first.content_hash == calculate_content_hash(first.content_jsonb)
    assert first.content_jsonb["sanitizer_policy_version"] == "v1.0.0"
    assert first.redaction_status == "redacted"


@pytest.mark.asyncio
@db_required
async def test_store_creates_ref_only_memory_record_and_non_exportable_artifact(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            result = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_request(),
            )

        row = await session.scalar(
            select(MemoryRecord).where(
                MemoryRecord.tenant_id == TENANT_ID,
                MemoryRecord.id == result.record.id,
            )
        )
        audit_count = await session.scalar(text("select count(*) from audit_events"))
        snapshot_count = await session.scalar(text("select count(*) from context_snapshots"))

    assert row is not None
    assert result.artifact.exportable is False
    assert result.artifact.content_hash == result.sanitized_payload.content_hash
    assert result.artifact.content_jsonb["payload"]["body"] == (
        "remember the implementation decision"
    )
    assert row.content_artifact_ref == f"artifact://memory/{result.artifact.id}"
    assert row.source_artifact_id == result.artifact.id
    assert row.content_hash == result.artifact.content_hash
    assert row.sanitizer_version_id is not None
    assert row.trust_level == "untrusted_content"
    assert row.data_class == "internal"
    assert result.sanitizer_policy_version == "v1.0.0"
    assert audit_count == 0
    assert snapshot_count == 0


@pytest.mark.asyncio
@db_required
async def test_store_denial_creates_no_memory_record_or_artifact(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)

        async with session.begin():
            with pytest.raises(MemoryStoreError, match="raw_secret_or_canary"):
                await MemoryStoreService(session).store(
                    tenant_id=TENANT_ID,
                    request=_request(payload={"body": "sk-" + "a" * 24}),
                )

        memory_count = await session.scalar(text("select count(*) from memory_records"))
        artifact_count = await session.scalar(text("select count(*) from artifacts"))

    assert memory_count == 0
    assert artifact_count == 0
