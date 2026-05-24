"""SP-020 T02 curator memory service foundation tests."""

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
from backend.app.db.models.artifact import Artifact
from backend.app.db.models.memory_record import MemoryRecord
from backend.app.db.session import create_engine
from backend.app.repositories.artifact import ArtifactRepository, calculate_content_hash
from backend.app.schemas.memory import MemoryCuratorRequest
from backend.app.services.memory.curator import MemoryCuratorError, MemoryCuratorService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000020201")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000020202")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000020203")
RUN_ID = UUID("00000000-0000-4000-8000-000000020210")
SOURCE_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000020220")

db_required = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _future_retention() -> datetime:
    return datetime.now(tz=UTC) + timedelta(days=30)


def _curator_request(**overrides: object) -> MemoryCuratorRequest:
    values: dict[str, object] = {
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
        "source_artifact_id": SOURCE_ARTIFACT_ID,
        "source_kind": "completed_run",
        "summary_ref": "artifact://summary/completed-run",
        "classification": {"external_origin": True},
        "retention_until": _future_retention(),
    }
    values.update(overrides)
    return MemoryCuratorRequest.model_validate(values)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-memory-curator",
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
            raise AssertionError("memory curator tests require PostgreSQL.") from exc
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
            values (:actor_id, 1, 'human', 'human:memory-curator',
                    'Memory Curator Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'memory-curator-workspace',
                    'memory-curator-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'memory-curator-project',
                    'memory-curator-project', 'active', '{"rls_ready": true}'::jsonb)
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
        {"config_hash": "6" * 64, "ruleset_hash": "7" * 64},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, status)
            values (:run_id, 1, :project_id, 'completed')
            """
        ),
        {"run_id": RUN_ID, "project_id": PROJECT_ID},
    )


async def _insert_source_artifact(session: AsyncSession) -> Artifact:
    source_payload = {
        "body": "source artifact body must not leak into curated memory",
        "verdict": "completed",
    }
    return await ArtifactRepository(session).create_artifact(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        project_id=PROJECT_ID,
        kind="other",
        content_hash=calculate_content_hash(source_payload),
        content_jsonb=source_payload,
        payload_data_class="internal",
        exportable=False,
    )


def test_curator_request_keeps_record_kind_and_memory_metadata_server_owned() -> None:
    _curator_request()
    for forbidden_field in (
        "record_kind",
        "content_artifact_ref",
        "content_hash",
        "data_class",
        "redaction_status",
        "sanitizer_version_id",
        "trust_level",
    ):
        with pytest.raises(ValidationError):
            MemoryCuratorRequest.model_validate(
                {
                    "project_id": PROJECT_ID,
                    "run_id": RUN_ID,
                    "source_artifact_id": SOURCE_ARTIFACT_ID,
                    "source_kind": "completed_run",
                    "summary_ref": "artifact://summary/completed-run",
                    "retention_until": _future_retention(),
                    forbidden_field: "caller-owned",
                }
            )


def test_curator_request_rejects_raw_summary_body() -> None:
    with pytest.raises(ValidationError, match="summary_ref"):
        _curator_request(summary_ref="completed run contained useful setup notes")


@pytest.mark.asyncio
@db_required
async def test_curator_creates_auto_completion_memory_without_raw_source_body(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            source_artifact = await _insert_source_artifact(session)
            result = await MemoryCuratorService(session).curate(
                tenant_id=TENANT_ID,
                request=_curator_request(source_artifact_id=source_artifact.id),
            )

        row = await session.scalar(
            select(MemoryRecord).where(
                MemoryRecord.tenant_id == TENANT_ID,
                MemoryRecord.id == result.stored.record.id,
            )
        )
        artifact_count = await session.scalar(text("select count(*) from artifacts"))

    assert row is not None
    assert row.record_kind == "auto_completion"
    assert row.source_artifact_id == source_artifact.id
    assert result.stored.artifact.exportable is False
    payload = result.stored.artifact.content_jsonb["payload"]
    assert payload["source_kind"] == "completed_run"
    assert payload["source"]["artifact_ref"] == f"artifact://source/{source_artifact.id}"
    assert payload["source"]["artifact_digest"] == source_artifact.content_hash
    assert payload["summary_ref"] == "artifact://summary/completed-run"
    assert "source artifact body must not leak" not in str(result.stored.artifact.content_jsonb)
    assert artifact_count == 2


@pytest.mark.asyncio
@db_required
async def test_curator_maps_review_finding_and_rejects_raw_summary_ref(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            source_artifact = await _insert_source_artifact(session)
            result = await MemoryCuratorService(session).curate(
                tenant_id=TENANT_ID,
                request=_curator_request(
                    source_artifact_id=source_artifact.id,
                    source_kind="review_finding",
                    summary_ref="artifact://summary/review-finding",
                    reason_code="codex_inline_finding_adopted",
                ),
            )

        async with session.begin():
            with pytest.raises(MemoryCuratorError, match="raw_secret_or_canary"):
                await MemoryCuratorService(session).curate(
                    tenant_id=TENANT_ID,
                    request=_curator_request(
                        source_artifact_id=source_artifact.id,
                        summary_ref="artifact://summary/sk-" + "a" * 24,
                    ),
                )

        memory_count = await session.scalar(text("select count(*) from memory_records"))

    assert result.stored.record.record_kind == "auto_review_finding"
    assert result.stored.artifact.content_jsonb["payload"]["reason_code"] == (
        "codex_inline_finding_adopted"
    )
    assert memory_count == 1


@pytest.mark.asyncio
@db_required
async def test_curator_rejects_missing_source_artifact_boundary(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            with pytest.raises(MemoryCuratorError, match="source_artifact_id"):
                await MemoryCuratorService(session).curate(
                    tenant_id=TENANT_ID,
                    request=_curator_request(source_artifact_id=uuid4()),
                )

        memory_count = await session.scalar(text("select count(*) from memory_records"))
        artifact_count = await session.scalar(text("select count(*) from artifacts"))

    assert memory_count == 0
    assert artifact_count == 0
