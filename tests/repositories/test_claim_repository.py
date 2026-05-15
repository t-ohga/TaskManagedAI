from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.repositories.claim import ClaimRepository
from backend.app.schemas.claim import ClaimCreate, ClaimUpdate

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000031001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000031002")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000031003")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000031004")
RESEARCH_TASK_A_ID = UUID("00000000-0000-4000-8000-000000031005")
RESEARCH_TASK_B_ID = UUID("00000000-0000-4000-8000-000000031006")


def _valid_prov() -> dict[str, object]:
    return {
        "activities": [{"id": "activity:research", "type": "prov:Activity"}],
        "entities": [{"id": "entity:claim", "type": "prov:Entity"}],
        "wasGeneratedBy": [{"entity": "entity:claim", "activity": "activity:research"}],
    }


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-claim-repository",
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
            raise AssertionError("Claim repository tests require PostgreSQL.") from exc
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
            truncate evidence_items, claims, evidence_sources, research_tasks,
              projects, workspaces, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_fixtures(session: AsyncSession) -> None:
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
            values (:actor_id, 1, 'human', 'human:research', 'Research Actor',
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'workspace', 'workspace', :actor_id,
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
              (:task_a_id, 1, :project_a_id, :actor_id, 'Research A', 'queued',
                '{"rls_ready": true}'::jsonb),
              (:task_b_id, 1, :project_b_id, :actor_id, 'Research B', 'queued',
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "task_a_id": RESEARCH_TASK_A_ID,
            "task_b_id": RESEARCH_TASK_B_ID,
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "actor_id": ACTOR_ID,
        },
    )


@pytest.mark.asyncio
async def test_claim_repository_crud(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)
        repo = ClaimRepository(session)

        created = await repo.create_claim(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            research_task_id=RESEARCH_TASK_A_ID,
            claim_create=ClaimCreate(
                claim_text="Claim A",
                provenance_json=_valid_prov(),
                freshness_score=0.5,
            ),
        )
        fetched = await repo.get_claim_by_id(1, PROJECT_A_ID, created.id)
        listed = await repo.list_claims_by_research_task(1, PROJECT_A_ID, RESEARCH_TASK_A_ID)
        updated = await repo.update_claim(
            1,
            PROJECT_A_ID,
            created.id,
            ClaimUpdate(claim_text="Claim A updated", freshness_score=0.75),
        )
        deleted = await repo.delete_claim(1, PROJECT_A_ID, created.id)
        missing = await repo.get_claim_by_id(1, PROJECT_A_ID, created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert [claim.id for claim in listed] == [created.id]
    assert updated is not None
    assert updated.claim_text == "Claim A updated"
    assert updated.freshness_score == 0.75
    assert deleted is True
    assert missing is None


@pytest.mark.asyncio
async def test_claim_repository_cross_project_select_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)
        repo = ClaimRepository(session)
        created = await repo.create_claim(
            1,
            PROJECT_A_ID,
            RESEARCH_TASK_A_ID,
            ClaimCreate(claim_text="Claim A", provenance_json=_valid_prov()),
        )

        result = await repo.get_claim_by_id(1, PROJECT_B_ID, created.id)

    assert result is None


@pytest.mark.asyncio
async def test_claim_repository_same_tenant_cross_project_select_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)
        repo = ClaimRepository(session)
        created = await repo.create_claim(
            1,
            PROJECT_B_ID,
            RESEARCH_TASK_B_ID,
            ClaimCreate(claim_text="Claim B", provenance_json=_valid_prov()),
        )

        result = await repo.get_claim_by_id(1, PROJECT_A_ID, created.id)

    assert result is None


@pytest.mark.asyncio
async def test_claim_repository_cross_project_insert_rejected_by_composite_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)
        repo = ClaimRepository(session)

        with pytest.raises(IntegrityError) as exc_info:
            await repo.create_claim(
                1,
                PROJECT_B_ID,
                RESEARCH_TASK_A_ID,
                ClaimCreate(claim_text="Cross project claim", provenance_json=_valid_prov()),
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="claims_research_task_fkey",
        )
        await session.rollback()
