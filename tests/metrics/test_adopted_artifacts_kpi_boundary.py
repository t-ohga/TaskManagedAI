from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
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
from backend.app.services.metrics.adopted_artifacts import (
    _CITATION_COVERAGE_SQL,
    AdoptedArtifactAttributionService,
    AdoptedArtifactCitationCoverageService,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-00000000f001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-00000000f010")
PROJECT_ID = UUID("00000000-0000-4000-8000-00000000f011")
PROJECT_TWO_ID = UUID("00000000-0000-4000-8000-00000000f012")
ROOT_RUN_ID = UUID("00000000-0000-4000-8000-00000000f101")
CHILD_RUN_ID = UUID("00000000-0000-4000-8000-00000000f102")
OTHER_RUN_ID = UUID("00000000-0000-4000-8000-00000000f103")
FINAL_ARTIFACT_ID = UUID("00000000-0000-4000-8000-00000000f201")
DRAFT_ARTIFACT_ID = UUID("00000000-0000-4000-8000-00000000f202")
UNLINKED_ARTIFACT_ID = UUID("00000000-0000-4000-8000-00000000f203")
OTHER_PROJECT_ARTIFACT_ID = UUID("00000000-0000-4000-8000-00000000f204")
FINAL_EVENT_ID = UUID("00000000-0000-4000-8000-00000000f301")
DRAFT_EVENT_ID = UUID("00000000-0000-4000-8000-00000000f302")
OTHER_EVENT_ID = UUID("00000000-0000-4000-8000-00000000f303")


def test_phase_e_pe_f_015_citation_coverage_sql_contract_is_exact() -> None:
    """PE-F-015: citation_coverage uses recursive lineage + final adoptions only."""

    sql = " ".join(_CITATION_COVERAGE_SQL.text.lower().split())

    assert "with recursive run_tree as" in sql
    assert (
        "join run_tree parent on parent.tenant_id = child.tenant_id "
        "and parent.project_id = child.project_id and parent.id = child.parent_run_id"
    ) in sql
    assert "where not child.id = any(parent.path)" in sql
    assert "from adopted_artifacts aa" in sql
    assert "aa.adoption_state = 'final'" in sql
    assert sql.count("aa.adoption_state = 'final'") == 1
    assert (
        "join artifacts a on a.tenant_id = aa.tenant_id and a.project_id = aa.project_id "
        "and a.run_id = aa.run_id and a.id = aa.artifact_id"
    ) in sql
    assert "fa.content_jsonb->'sample_claims'" in sql
    assert "fa.content_jsonb#>'{input,sample_claims}'" in sql
    assert "count(*) filter (where has_citation is true)::float / count(*)::float" in sql


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-adopted-artifacts",
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
    except (OSError, SQLAlchemyError, TimeoutError, Exception) as exc:
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("adopted artifact KPI tests require PostgreSQL.") from exc
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
              adopted_artifacts,
              artifacts,
              agent_run_events,
              agent_runs,
              projects,
              workspaces,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _seed_project_boundary(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (:tenant_id, 'tenant-one', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"tenant_id": TENANT_ID},
    )
    await session.execute(
        text(
            """
            insert into policy_profiles (tenant_id, profile_id, description)
            values (:tenant_id, 'default', 'default profile')
            on conflict (tenant_id, profile_id) do nothing
            """
        ),
        {"tenant_id": TENANT_ID},
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:actor_id, :tenant_id, 'agent', 'agent:adoption',
                    'Adoption Agent', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"tenant_id": TENANT_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, :tenant_id, 'adoption', 'Adoption',
                    :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "workspace_id": WORKSPACE_ID,
            "tenant_id": TENANT_ID,
            "actor_id": ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into projects (
              id, tenant_id, workspace_id, slug, name, status, policy_profile, metadata
            )
            values
              (:project_id, :tenant_id, :workspace_id, 'adoption', 'Adoption',
               'active', 'default', '{"rls_ready": true}'::jsonb),
              (:project_two_id, :tenant_id, :workspace_id, 'other-adoption',
               'Other Adoption', 'active', 'default', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "project_id": PROJECT_ID,
            "project_two_id": PROJECT_TWO_ID,
            "tenant_id": TENANT_ID,
            "workspace_id": WORKSPACE_ID,
        },
    )


async def _seed_runs(session: AsyncSession) -> None:
    base = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    await session.execute(
        text(
            """
            insert into agent_runs (
              id, tenant_id, project_id, parent_run_id, status, completed_at,
              role_id, role_scope, cost_usd, tokens_input, tokens_output,
              created_at, updated_at
            )
            values
              (:root_run_id, :tenant_id, :project_id, null, 'completed',
               :base, 'orchestrator', 'project', 0, 0, 0, :base, :base),
              (:child_run_id, :tenant_id, :project_id, :root_run_id, 'completed',
               :base, 'implementer', 'project', 0, 0, 0, :base, :base),
              (:other_run_id, :tenant_id, :project_two_id, null, 'completed',
               :base, 'orchestrator', 'project', 0, 0, 0, :base, :base)
            """
        ),
        {
            "tenant_id": TENANT_ID,
            "project_id": PROJECT_ID,
            "project_two_id": PROJECT_TWO_ID,
            "root_run_id": ROOT_RUN_ID,
            "child_run_id": CHILD_RUN_ID,
            "other_run_id": OTHER_RUN_ID,
            "base": base,
        },
    )


async def _insert_artifact(
    session: AsyncSession,
    *,
    artifact_id: UUID,
    project_id: UUID,
    run_id: UUID,
    sample_claims: list[dict[str, object]],
) -> None:
    content_jsonb = {"sample_claims": sample_claims}
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
            "artifact_id": artifact_id,
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "run_id": run_id,
            "content_hash": calculate_content_hash(content_jsonb),
            "content_jsonb": json.dumps(content_jsonb),
        },
    )


async def _insert_artifact_generated_event(
    session: AsyncSession,
    *,
    event_id: UUID,
    run_id: UUID,
    seq_no: int,
    artifact_id: UUID,
    adoption_state: str,
) -> None:
    await session.execute(
        text(
            """
            insert into agent_run_events (
              id, tenant_id, run_id, seq_no, event_type, event_payload,
              actor_id, idempotency_key, created_at
            )
            values (
              :event_id, :tenant_id, :run_id, :seq_no, 'artifact_generated',
              cast(:event_payload as jsonb), :actor_id, :idempotency_key, :created_at
            )
            """
        ),
        {
            "event_id": event_id,
            "tenant_id": TENANT_ID,
            "run_id": run_id,
            "seq_no": seq_no,
            "actor_id": ACTOR_ID,
            "idempotency_key": f"artifact-generated-{event_id}",
            "created_at": datetime(2026, 5, 24, 12, seq_no, tzinfo=UTC),
            "event_payload": json.dumps(
                {
                    "artifact_id": str(artifact_id),
                    "adoption_state": adoption_state,
                }
            ),
        },
    )


async def _seed_fixture(session: AsyncSession) -> None:
    await _reset_tables(session)
    await _seed_project_boundary(session)
    await _seed_runs(session)
    await _insert_artifact(
        session,
        artifact_id=FINAL_ARTIFACT_ID,
        project_id=PROJECT_ID,
        run_id=CHILD_RUN_ID,
        sample_claims=[
            {"claim_id": "final-covered", "citation_ids": ["source-1"]},
            {"claim_id": "final-uncovered", "citation_ids": []},
        ],
    )
    await _insert_artifact(
        session,
        artifact_id=DRAFT_ARTIFACT_ID,
        project_id=PROJECT_ID,
        run_id=CHILD_RUN_ID,
        sample_claims=[
            {"claim_id": "draft-covered-1", "citation_ids": ["source-2"]},
            {"claim_id": "draft-covered-2", "citation_ids": ["source-3"]},
        ],
    )
    await _insert_artifact(
        session,
        artifact_id=UNLINKED_ARTIFACT_ID,
        project_id=PROJECT_ID,
        run_id=CHILD_RUN_ID,
        sample_claims=[
            {"claim_id": "unlinked-covered-1", "citation_ids": ["source-4"]},
            {"claim_id": "unlinked-covered-2", "citation_ids": ["source-5"]},
        ],
    )
    await _insert_artifact(
        session,
        artifact_id=OTHER_PROJECT_ARTIFACT_ID,
        project_id=PROJECT_TWO_ID,
        run_id=OTHER_RUN_ID,
        sample_claims=[{"claim_id": "other-project", "citation_ids": ["source-6"]}],
    )
    await _insert_artifact_generated_event(
        session,
        event_id=FINAL_EVENT_ID,
        run_id=CHILD_RUN_ID,
        seq_no=1,
        artifact_id=FINAL_ARTIFACT_ID,
        adoption_state="final",
    )
    await _insert_artifact_generated_event(
        session,
        event_id=DRAFT_EVENT_ID,
        run_id=CHILD_RUN_ID,
        seq_no=2,
        artifact_id=DRAFT_ARTIFACT_ID,
        adoption_state="draft",
    )
    await _insert_artifact_generated_event(
        session,
        event_id=OTHER_EVENT_ID,
        run_id=OTHER_RUN_ID,
        seq_no=1,
        artifact_id=OTHER_PROJECT_ARTIFACT_ID,
        adoption_state="final",
    )
    await session.commit()


@pytest.mark.asyncio
async def test_citation_coverage_uses_only_final_adopted_artifacts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_fixture(session)
        service = AdoptedArtifactAttributionService(session)
        await service.record_adoption(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            run_id=CHILD_RUN_ID,
            artifact_id=FINAL_ARTIFACT_ID,
            adopted_by_actor_id=ACTOR_ID,
            adoption_state="final",
            adoption_event_id=FINAL_EVENT_ID,
            finalized_at=datetime(2026, 5, 24, 12, 30, tzinfo=UTC),
        )
        await service.record_adoption(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            run_id=CHILD_RUN_ID,
            artifact_id=DRAFT_ARTIFACT_ID,
            adopted_by_actor_id=ACTOR_ID,
            adoption_state="draft",
        )

        result = await AdoptedArtifactCitationCoverageService(session).fetch(
            tenant_id=TENANT_ID,
            root_run_id=ROOT_RUN_ID,
        )

    assert result is not None
    assert result.project_id == PROJECT_ID
    assert result.lineage_run_count == 2
    assert result.final_adopted_artifact_count == 1
    assert result.citation_total_claim_count == 2
    assert result.citation_covered_claim_count == 1
    assert result.citation_coverage == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_record_adoption_rejects_cross_project_artifact(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_fixture(session)

        with pytest.raises(ValueError, match="tenant_id \\+ project_id \\+ run_id"):
            await AdoptedArtifactAttributionService(session).record_adoption(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                run_id=CHILD_RUN_ID,
                artifact_id=OTHER_PROJECT_ARTIFACT_ID,
                adopted_by_actor_id=ACTOR_ID,
                adoption_state="final",
                adoption_event_id=OTHER_EVENT_ID,
                finalized_at=datetime(2026, 5, 24, 12, 30, tzinfo=UTC),
            )


@pytest.mark.asyncio
async def test_final_adoption_requires_matching_final_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_fixture(session)

        with pytest.raises(ValueError, match="adoption_state=final"):
            await AdoptedArtifactAttributionService(session).record_adoption(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                run_id=CHILD_RUN_ID,
                artifact_id=DRAFT_ARTIFACT_ID,
                adopted_by_actor_id=ACTOR_ID,
                adoption_state="final",
                adoption_event_id=DRAFT_EVENT_ID,
                finalized_at=datetime(2026, 5, 24, 12, 30, tzinfo=UTC),
            )


@pytest.mark.asyncio
async def test_record_adoption_rejects_secret_shaped_metadata(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_fixture(session)

        with pytest.raises(ValueError, match="prohibited key"):
            await AdoptedArtifactAttributionService(session).record_adoption(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                run_id=CHILD_RUN_ID,
                artifact_id=FINAL_ARTIFACT_ID,
                adopted_by_actor_id=ACTOR_ID,
                adoption_state="final",
                adoption_event_id=FINAL_EVENT_ID,
                finalized_at=datetime(2026, 5, 24, 12, 30, tzinfo=UTC),
                metadata={"raw_secret": "placeholder"},
            )
