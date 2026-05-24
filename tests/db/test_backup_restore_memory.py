"""SP-018/SP-020 memory backup/restore drill regressions."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.repositories.artifact import calculate_content_hash
from backend.app.schemas.memory import MemoryArchivePolicyRequest, MemoryInsightRequest
from backend.app.services.memory.archive_policy import MemoryArchivePolicyService
from backend.app.services.memory.insights import MemoryInsightService
from backend.app.services.memory.retrieval import (
    MemoryRetrievalDenied,
    MemoryRetrievalService,
)
from backend.app.services.memory.store import MemoryStoreService
from backend.app.services.metrics.adopted_artifacts import (
    AdoptedArtifactAttributionService,
    AdoptedArtifactCitationCoverageService,
)
from tests.memory.test_retrieval_pipeline import (
    ACTOR_ID,
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
SP020_FINAL_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000020801")
SP020_FINAL_ADOPTION_EVENT_ID = UUID("00000000-0000-4000-8000-000000020802")

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


def _archive_request(**overrides: object) -> MemoryArchivePolicyRequest:
    values: dict[str, object] = {
        "project_id": PROJECT_ID,
        "minimum_age_days": 30,
        "max_records": 100,
    }
    values.update(overrides)
    return MemoryArchivePolicyRequest.model_validate(values)


def _insight_request(**overrides: object) -> MemoryInsightRequest:
    values: dict[str, object] = {
        "project_id": PROJECT_ID,
        "limit": 20,
    }
    values.update(overrides)
    return MemoryInsightRequest.model_validate(values)


async def _set_memory_window(
    session: AsyncSession,
    *,
    record_id: UUID,
    reference_at: datetime,
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
            "created_at": reference_at - timedelta(days=days_old),
            "retention_until": reference_at + timedelta(days=30),
            "tenant_id": TENANT_ID,
            "record_id": record_id,
        },
    )


async def _insert_sp020_final_artifact_fixture(
    session: AsyncSession,
    *,
    finalized_at: datetime,
) -> None:
    content_jsonb = {
        "sample_claims": [
            {"claim_id": "restore-covered", "citation_ids": ["source-restore-1"]},
            {"claim_id": "restore-uncovered", "citation_ids": []},
        ]
    }
    await session.execute(
        text(
            """
            insert into artifacts (
              id, tenant_id, project_id, run_id, kind, content_hash, content_jsonb,
              payload_data_class, trust_level, exportable
            )
            values (
              :artifact_id, :tenant_id, :project_id, :run_id, 'other',
              :content_hash, cast(:content_jsonb as jsonb),
              'internal', 'validated_artifact', true
            )
            """
        ),
        {
            "artifact_id": SP020_FINAL_ARTIFACT_ID,
            "tenant_id": TENANT_ID,
            "project_id": PROJECT_ID,
            "run_id": RUN_ID,
            "content_hash": calculate_content_hash(content_jsonb),
            "content_jsonb": json.dumps(content_jsonb),
        },
    )
    await session.execute(
        text(
            """
            insert into agent_run_events (
              id, tenant_id, run_id, seq_no, event_type, event_payload,
              actor_id, idempotency_key, created_at
            )
            values (
              :event_id, :tenant_id, :run_id, 1, 'artifact_generated',
              cast(:event_payload as jsonb), :actor_id, :idempotency_key, :created_at
            )
            """
        ),
        {
            "event_id": SP020_FINAL_ADOPTION_EVENT_ID,
            "tenant_id": TENANT_ID,
            "run_id": RUN_ID,
            "actor_id": ACTOR_ID,
            "idempotency_key": "sp020-restore-drill:final-artifact",
            "created_at": finalized_at,
            "event_payload": json.dumps(
                {
                    "artifact_id": str(SP020_FINAL_ARTIFACT_ID),
                    "adoption_state": "final",
                }
            ),
        },
    )


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


@pytest.mark.asyncio
async def test_sp020_restore_drill_preserves_archive_adoption_and_insight_refs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    drill_at = datetime.now(tz=UTC)

    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            archived = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(
                    record_kind="auto_completion",
                    payload={"body": "sp020 archive candidate body must stay hidden"},
                ),
            )
            active = await MemoryStoreService(session).store(
                tenant_id=TENANT_ID,
                request=_store_request(
                    record_kind="auto_failure",
                    payload={"body": "sp020 insight candidate body must stay hidden"},
                ),
            )
            archived_record_id = archived.record.id
            active_record_id = active.record.id
            active_source_artifact_id = active.record.source_artifact_id
            await _set_memory_window(
                session,
                record_id=archived_record_id,
                reference_at=drill_at,
                days_old=45,
            )
            await _set_memory_window(
                session,
                record_id=active_record_id,
                reference_at=drill_at,
                days_old=3,
            )
            archive_result = await MemoryArchivePolicyService(session).archive_low_value(
                tenant_id=TENANT_ID,
                request=_archive_request(),
                evaluated_at=drill_at,
            )
            archived_ids = tuple(record.id for record in archive_result.archived_records)

            await _insert_sp020_final_artifact_fixture(session, finalized_at=drill_at)
            adoption = await AdoptedArtifactAttributionService(session).record_adoption(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                run_id=RUN_ID,
                artifact_id=SP020_FINAL_ARTIFACT_ID,
                adopted_by_actor_id=ACTOR_ID,
                adoption_state="final",
                adoption_event_id=SP020_FINAL_ADOPTION_EVENT_ID,
                finalized_at=drill_at,
            )
            retrieval_result = await MemoryRetrievalService(session).retrieve(
                tenant_id=TENANT_ID,
                request=_retrieval_request(),
            )
            session.expire_all()
            insight_result = await MemoryInsightService(session).summarize(
                tenant_id=TENANT_ID,
                request=_insight_request(),
                generated_at=drill_at,
            )
            citation_result = await AdoptedArtifactCitationCoverageService(
                session
            ).fetch(
                tenant_id=TENANT_ID,
                root_run_id=RUN_ID,
            )

        relation = (
            await session.execute(
                text(
                    """
                    select
                      archived_mr.archived_at as archived_at,
                      archived_source.id as archived_source_artifact_id,
                      active_source.id as insight_source_artifact_id,
                      active_source.content_hash as insight_source_artifact_hash,
                      active_mr.content_hash as active_memory_hash,
                      aa.id as adopted_artifact_row_id,
                      aa.adoption_state as adoption_state,
                      aa.artifact_id as adopted_artifact_id,
                      aa.adoption_event_id as adoption_event_id,
                      adopted_artifact.id as adopted_artifact_fk_id,
                      adoption_event.id as adoption_event_fk_id,
                      adoption_event.event_payload->>'artifact_id'
                        as adoption_event_artifact_id
                    from memory_records archived_mr
                    join memory_records active_mr
                      on active_mr.tenant_id = archived_mr.tenant_id
                     and active_mr.project_id = archived_mr.project_id
                     and active_mr.id = :active_record_id
                    left join artifacts archived_source
                      on archived_source.tenant_id = archived_mr.tenant_id
                     and archived_source.project_id = archived_mr.project_id
                     and archived_source.id = archived_mr.source_artifact_id
                    left join artifacts active_source
                      on active_source.tenant_id = active_mr.tenant_id
                     and active_source.project_id = active_mr.project_id
                     and active_source.id = active_mr.source_artifact_id
                    join adopted_artifacts aa
                      on aa.tenant_id = archived_mr.tenant_id
                     and aa.project_id = archived_mr.project_id
                     and aa.id = :adopted_artifact_row_id
                    left join artifacts adopted_artifact
                      on adopted_artifact.tenant_id = aa.tenant_id
                     and adopted_artifact.project_id = aa.project_id
                     and adopted_artifact.run_id = aa.run_id
                     and adopted_artifact.id = aa.artifact_id
                    left join agent_run_events adoption_event
                      on adoption_event.tenant_id = aa.tenant_id
                     and adoption_event.run_id = aa.run_id
                     and adoption_event.id = aa.adoption_event_id
                    where archived_mr.tenant_id = :tenant_id
                      and archived_mr.project_id = :project_id
                      and archived_mr.id = :archived_record_id
                    """
                ),
                {
                    "tenant_id": TENANT_ID,
                    "project_id": PROJECT_ID,
                    "archived_record_id": archived_record_id,
                    "active_record_id": active_record_id,
                    "adopted_artifact_row_id": adoption.id,
                },
            )
        ).mappings().one()

    assert archived_ids == (archived_record_id,)
    assert [record.id for record in retrieval_result.records] == [active_record_id]
    assert [item.memory_record_id for item in insight_result.items] == [active_record_id]
    assert insight_result.items[0].source_artifact_ref == (
        f"artifact://source/{active_source_artifact_id}"
    )
    assert citation_result is not None
    assert citation_result.lineage_run_count == 1
    assert citation_result.final_adopted_artifact_count == 1
    assert citation_result.citation_total_claim_count == 2
    assert citation_result.citation_covered_claim_count == 1
    assert citation_result.citation_coverage == pytest.approx(0.5)

    assert relation["archived_at"] == drill_at
    assert relation["archived_source_artifact_id"] is not None
    assert relation["insight_source_artifact_id"] == active_source_artifact_id
    assert relation["insight_source_artifact_hash"] == relation["active_memory_hash"]
    assert relation["adopted_artifact_row_id"] == adoption.id
    assert relation["adoption_state"] == "final"
    assert relation["adopted_artifact_id"] == SP020_FINAL_ARTIFACT_ID
    assert relation["adoption_event_id"] == SP020_FINAL_ADOPTION_EVENT_ID
    assert relation["adopted_artifact_fk_id"] == SP020_FINAL_ARTIFACT_ID
    assert relation["adoption_event_fk_id"] == SP020_FINAL_ADOPTION_EVENT_ID
    assert relation["adoption_event_artifact_id"] == str(SP020_FINAL_ARTIFACT_ID)
    serialized_outputs = f"{retrieval_result!r} {insight_result!r}"
    assert "sp020 archive candidate body" not in serialized_outputs
    assert "sp020 insight candidate body" not in serialized_outputs
