"""SP-018 T07 memory backup/restore drill regression."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.services.memory.retrieval import (
    MemoryRetrievalDenied,
    MemoryRetrievalService,
)
from backend.app.services.memory.store import MemoryStoreService
from tests.memory.test_retrieval_pipeline import (
    CONTEXT_SNAPSHOT_ID,
    PROJECT_ID,
    RUN_ID,
    TENANT_ID,
    _insert_context_snapshot,
    _insert_fixture,
    _retrieval_request,
    _store_request,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-memory-backup-restore",
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
            raise AssertionError("memory backup/restore tests require PostgreSQL.") from exc
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


@pytest.mark.asyncio
async def test_memory_restore_drill_verifies_required_relationships(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            stored = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(),
            )
            await _insert_context_snapshot(
                session,
                snapshot_id=CONTEXT_SNAPSHOT_ID,
                run_id=RUN_ID,
            )
            result = await MemoryRetrievalService(session).retrieve(
                tenant_id=TENANT_ID,
                request=_retrieval_request(memory_record_ids=(stored.record.id,)),
                context_snapshot_id=CONTEXT_SNAPSHOT_ID,
            )

        relation = (
            await session.execute(
                text(
                    """
                    select
                      mr.content_hash as memory_hash,
                      source_artifact.content_hash as source_artifact_hash,
                      mra.retrieval_hash as retrieval_hash,
                      retrieval_artifact.content_hash as retrieval_artifact_hash,
                      mr_sanitizer.config_hash as memory_sanitizer_config_hash,
                      retrieval_sanitizer.config_hash as retrieval_sanitizer_config_hash,
                      mra.context_snapshot_id as context_snapshot_id
                    from memory_records mr
                    join artifacts source_artifact
                      on source_artifact.tenant_id = mr.tenant_id
                     and source_artifact.project_id = mr.project_id
                     and source_artifact.id = mr.source_artifact_id
                    join memory_retrieval_artifacts mra
                      on mra.tenant_id = mr.tenant_id
                     and mra.project_id = mr.project_id
                     and mra.memory_record_id = mr.id
                    join artifacts retrieval_artifact
                      on retrieval_artifact.tenant_id = mra.tenant_id
                     and retrieval_artifact.project_id = mra.project_id
                     and retrieval_artifact.id = cast(
                       replace(mra.retrieval_artifact_ref,
                               'artifact://memory-retrieval/', '') as uuid
                     )
                    join sanitizer_policy_versions mr_sanitizer
                      on mr_sanitizer.tenant_id = mr.tenant_id
                     and mr_sanitizer.id = mr.sanitizer_version_id
                    join sanitizer_policy_versions retrieval_sanitizer
                      on retrieval_sanitizer.tenant_id = mra.tenant_id
                     and retrieval_sanitizer.id = mra.sanitizer_version_id
                    where mr.tenant_id = :tenant_id
                      and mr.project_id = :project_id
                      and mr.id = :memory_record_id
                    """
                ),
                {
                    "tenant_id": TENANT_ID,
                    "project_id": PROJECT_ID,
                    "memory_record_id": stored.record.id,
                },
            )
        ).mappings().one()

    assert relation["memory_hash"] == relation["source_artifact_hash"]
    assert relation["retrieval_hash"] == relation["retrieval_artifact_hash"]
    assert relation["memory_sanitizer_config_hash"] == relation[
        "retrieval_sanitizer_config_hash"
    ]
    assert relation["context_snapshot_id"] == CONTEXT_SNAPSHOT_ID
    assert result.artifact is not None
    assert "raw memory content" not in str(result.artifact.content_jsonb)


@pytest.mark.asyncio
async def test_memory_restore_drill_denies_stale_sanitizer_config_hash(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            stored = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(),
            )
            await session.execute(
                text(
                    """
                    update sanitizer_policy_versions
                       set deprecated_at = now()
                     where tenant_id = :tenant_id
                       and deprecated_at is null
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
            await session.execute(
                text(
                    """
                    insert into sanitizer_policy_versions (
                      tenant_id, version, config_hash, ruleset_hash
                    )
                    values (1, 'v2.0.0', :config_hash, :ruleset_hash)
                    """
                ),
                {"config_hash": "b" * 64, "ruleset_hash": "c" * 64},
            )
            with pytest.raises(MemoryRetrievalDenied, match="stale_sanitizer"):
                await MemoryRetrievalService(session).retrieve(
                    tenant_id=TENANT_ID,
                    request=_retrieval_request(memory_record_ids=(stored.record.id,)),
                )

        retrieval_count = await session.scalar(
            text("select count(*) from memory_retrieval_artifacts")
        )

    assert retrieval_count == 0
