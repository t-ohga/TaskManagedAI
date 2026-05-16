from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
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
from backend.app.services.research.citation_coverage import compute_citation_coverage

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[3]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000037001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000037002")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000037003")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000037004")
RESEARCH_TASK_A_ID = UUID("00000000-0000-4000-8000-000000037005")
RESEARCH_TASK_OTHER_A_ID = UUID("00000000-0000-4000-8000-000000037006")
RESEARCH_TASK_B_ID = UUID("00000000-0000-4000-8000-000000037007")
SOURCE_ID = UUID("00000000-0000-4000-8000-000000037008")
VALID_HASH = "e" * 64


def _uuid(offset: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{offset:012x}")


def _valid_prov(index: int) -> dict[str, object]:
    return {
        "activities": [{"id": f"activity:{index}", "type": "prov:Activity"}],
        "entities": [{"id": f"entity:{index}", "type": "prov:Entity"}],
        "wasGeneratedBy": [{"entity": f"entity:{index}", "activity": f"activity:{index}"}],
    }


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-citation-coverage",
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
            raise AssertionError("Citation coverage tests require PostgreSQL.") from exc
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
            truncate evidence_items, claims, evidence_sources, research_tasks,
              projects, workspaces, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_base_fixture(session: AsyncSession) -> None:
    await _reset_tables(session)
    await session.execute(
        text(
            "insert into tenants (id, name, metadata) "
            "values (1, 'tenant-one', '{\"rls_ready\": true}'::jsonb)"
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:actor_id, 1, 'human', 'human:citation', 'Citation Actor',
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'citation', 'citation', :actor_id,
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:project_a_id, 1, :workspace_id, 'project-a', 'project-a', 'active',
                '{"rls_ready": true}'::jsonb),
              (:project_b_id, 1, :workspace_id, 'project-b', 'project-b', 'active',
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "workspace_id": WORKSPACE_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into research_tasks (
              id, tenant_id, project_id, created_by_actor_id, title, status, metadata
            )
            values
              (:task_a_id, 1, :project_a_id, :actor_id, 'Research A', 'completed',
                '{"rls_ready": true}'::jsonb),
              (:task_other_a_id, 1, :project_a_id, :actor_id, 'Research Other A', 'completed',
                '{"rls_ready": true}'::jsonb),
              (:task_b_id, 1, :project_b_id, :actor_id, 'Research B', 'completed',
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "task_a_id": RESEARCH_TASK_A_ID,
            "task_other_a_id": RESEARCH_TASK_OTHER_A_ID,
            "task_b_id": RESEARCH_TASK_B_ID,
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "actor_id": ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into evidence_sources (
              id, tenant_id, canonical_url, content_hash, retrieved_at, metadata
            )
            values (
              :source_id, 1, 'https://example.com/source', :content_hash,
              timestamptz '2026-05-16 00:00:00+00', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"source_id": SOURCE_ID, "content_hash": VALID_HASH},
    )


async def _insert_claims(
    session: AsyncSession,
    *,
    project_id: UUID = PROJECT_A_ID,
    research_task_id: UUID = RESEARCH_TASK_A_ID,
    evidence_flags: tuple[bool, ...],
    offset: int = 0,
) -> None:
    claim_rows = []
    evidence_rows = []
    for index, has_evidence in enumerate(evidence_flags):
        absolute_index = offset + index
        claim_id = _uuid(0x370100 + absolute_index)
        claim_rows.append(
            {
                "claim_id": claim_id,
                "project_id": project_id,
                "task_id": research_task_id,
                "claim_text": f"Claim {absolute_index}",
                "prov": json.dumps(_valid_prov(absolute_index)),
            }
        )
        if has_evidence:
            evidence_rows.append(
                {
                    "item_id": _uuid(0x370200 + absolute_index),
                    "project_id": project_id,
                    "claim_id": claim_id,
                    "source_id": SOURCE_ID,
                    "locator": f"p.{absolute_index}",
                }
            )

    if claim_rows:
        await session.execute(
            text(
                """
                insert into claims (
                  id, tenant_id, project_id, research_task_id, claim_text, provenance_json, metadata
                )
                values (
                  :claim_id, 1, :project_id, :task_id, :claim_text,
                  cast(:prov as jsonb), '{"rls_ready": true}'::jsonb
                )
                """
            ),
            claim_rows,
        )

    if evidence_rows:
        await session.execute(
            text(
                """
                insert into evidence_items (
                  id, tenant_id, project_id, claim_id, source_id, locator, relation, metadata
                )
                values (
                  :item_id, 1, :project_id, :claim_id, :source_id, :locator, 'supports',
                  '{"rls_ready": true}'::jsonb
                )
                """
            ),
            evidence_rows,
        )


@pytest.mark.asyncio
async def test_one_claim_with_one_evidence_item_has_full_coverage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)
        await _insert_claims(session, evidence_flags=(True,))

        metric = await compute_citation_coverage(session, 1, PROJECT_A_ID, RESEARCH_TASK_A_ID)

    assert metric.numerator == 1
    assert metric.denominator == 1
    assert metric.coverage == 1.0


@pytest.mark.asyncio
async def test_one_claim_without_evidence_item_has_zero_coverage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)
        await _insert_claims(session, evidence_flags=(False,))

        metric = await compute_citation_coverage(session, 1, PROJECT_A_ID, RESEARCH_TASK_A_ID)

    assert metric.numerator == 0
    assert metric.denominator == 1
    assert metric.coverage == 0.0


@pytest.mark.asyncio
async def test_two_claims_one_with_evidence_item_has_half_coverage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)
        await _insert_claims(session, evidence_flags=(True, False))

        metric = await compute_citation_coverage(session, 1, PROJECT_A_ID, RESEARCH_TASK_A_ID)

    assert metric.numerator == 1
    assert metric.denominator == 2
    assert metric.coverage == 0.5


@pytest.mark.asyncio
async def test_zero_claims_returns_none_coverage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)

        metric = await compute_citation_coverage(session, 1, PROJECT_A_ID, RESEARCH_TASK_A_ID)

    assert metric.numerator == 0
    assert metric.denominator == 0
    assert metric.coverage is None


@pytest.mark.asyncio
async def test_cross_project_research_task_reference_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)

        with pytest.raises(ValueError, match="research_task_id not reachable in tenant/project"):
            await compute_citation_coverage(session, 1, PROJECT_B_ID, RESEARCH_TASK_A_ID)


@pytest.mark.asyncio
async def test_evidence_on_other_claim_does_not_cover_target_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)
        await _insert_claims(session, evidence_flags=(False,))
        await _insert_claims(
            session,
            research_task_id=RESEARCH_TASK_OTHER_A_ID,
            evidence_flags=(True,),
            offset=10,
        )

        metric = await compute_citation_coverage(session, 1, PROJECT_A_ID, RESEARCH_TASK_A_ID)

    assert metric.numerator == 0
    assert metric.denominator == 1
    assert metric.coverage == 0.0
