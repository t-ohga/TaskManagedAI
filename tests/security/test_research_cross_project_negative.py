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
from backend.app.repositories.evidence_item import EvidenceItemRepository
from backend.app.schemas.claim import ClaimCreate
from backend.app.schemas.evidence_item import EvidenceItemCreate

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000033001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000033002")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000033003")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000033004")
RESEARCH_TASK_A_ID = UUID("00000000-0000-4000-8000-000000033005")
RESEARCH_TASK_B_ID = UUID("00000000-0000-4000-8000-000000033006")
CLAIM_A_ID = UUID("00000000-0000-4000-8000-000000033007")
CLAIM_B_ID = UUID("00000000-0000-4000-8000-000000033008")
SOURCE_ID = UUID("00000000-0000-4000-8000-000000033009")
EVIDENCE_ITEM_A_ID = UUID("00000000-0000-4000-8000-000000033010")
VALID_HASH = "b" * 64


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
        dev_login_cookie_secret="test-cookie-secret-for-research-cross-project",
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
            raise AssertionError("Research cross-project tests require PostgreSQL.") from exc
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


def _constraint_name(error: BaseException) -> str | None:
    return (
        getattr(error, "constraint_name", None)
        or getattr(getattr(error, "orig", None), "constraint_name", None)
        or getattr(getattr(getattr(error, "orig", None), "__cause__", None), "constraint_name", None)
    )


def _assert_integrity_error(
    error: IntegrityError,
    *,
    sqlstate: str,
    constraint_name: str,
) -> None:
    assert _sqlstate(error) == sqlstate
    assert _constraint_name(error) == constraint_name


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
            "insert into tenants (id, name, metadata) "
            "values (1, 'tenant-one', '{\"rls_ready\": true}'::jsonb)"
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
    await session.execute(
        text(
            """
            insert into claims (
              id, tenant_id, project_id, research_task_id, claim_text, provenance_json, metadata
            )
            values
              (:claim_a_id, 1, :project_a_id, :task_a_id, 'Claim A',
                '{"activities":[{"id":"activity:research","type":"prov:Activity"}],"entities":[{"id":"entity:claim","type":"prov:Entity"}],"wasGeneratedBy":[{"entity":"entity:claim","activity":"activity:research"}]}'::jsonb,
                '{"rls_ready": true}'::jsonb),
              (:claim_b_id, 1, :project_b_id, :task_b_id, 'Claim B',
                '{"activities":[{"id":"activity:research","type":"prov:Activity"}],"entities":[{"id":"entity:claim","type":"prov:Entity"}],"wasGeneratedBy":[{"entity":"entity:claim","activity":"activity:research"}]}'::jsonb,
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "claim_a_id": CLAIM_A_ID,
            "claim_b_id": CLAIM_B_ID,
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "task_a_id": RESEARCH_TASK_A_ID,
            "task_b_id": RESEARCH_TASK_B_ID,
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
    await session.execute(
        text(
            """
            insert into evidence_items (
              id, tenant_id, project_id, claim_id, source_id, locator, relation, metadata
            )
            values (
              :item_id, 1, :project_a_id, :claim_a_id, :source_id, 'p.1', 'supports',
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "item_id": EVIDENCE_ITEM_A_ID,
            "project_a_id": PROJECT_A_ID,
            "claim_a_id": CLAIM_A_ID,
            "source_id": SOURCE_ID,
        },
    )


@pytest.mark.asyncio
async def test_claims_cross_project_select_and_insert_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)
        repo = ClaimRepository(session)

        assert await repo.get_claim_by_id(1, PROJECT_B_ID, CLAIM_A_ID) is None

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


@pytest.mark.asyncio
async def test_evidence_items_cross_project_select_and_insert_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)
        repo = EvidenceItemRepository(session)

        assert await repo.get_evidence_item_by_id(1, PROJECT_B_ID, EVIDENCE_ITEM_A_ID) is None
        assert await repo.list_evidence_items_by_claim(1, PROJECT_B_ID, CLAIM_A_ID) == []

        with pytest.raises(IntegrityError) as exc_info:
            await repo.create_evidence_item(
                1,
                PROJECT_B_ID,
                CLAIM_A_ID,
                EvidenceItemCreate(source_id=SOURCE_ID, locator="p.cross", relation="supports"),
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="evidence_items_claim_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_same_tenant_other_project_research_task_attach_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)
        repo = ClaimRepository(session)

        with pytest.raises(IntegrityError) as exc_info:
            await repo.create_claim(
                1,
                PROJECT_A_ID,
                RESEARCH_TASK_B_ID,
                ClaimCreate(claim_text="Wrong research task", provenance_json=_valid_prov()),
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="claims_research_task_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_same_tenant_other_project_claim_attach_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)
        repo = EvidenceItemRepository(session)

        with pytest.raises(IntegrityError) as exc_info:
            await repo.create_evidence_item(
                1,
                PROJECT_A_ID,
                CLAIM_B_ID,
                EvidenceItemCreate(source_id=SOURCE_ID, locator="p.cross", relation="supports"),
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="evidence_items_claim_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_research_tasks_cross_project_select_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Task A must be reachable only via its real project_id (Project A).

    F-PR22-R2-006 P2 adopt: assert positive reachability via Project A
    first so the negative-case ``project_id=B AND id=A`` empty result is
    proven to come from the project_id filter, not from an impossible
    data predicate. Without the positive control, this test would pass
    even if no isolation enforcement existed at all.
    """

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

        # Positive control: Task A is reachable via its real project_id (A).
        reachable_via_a = await session.scalar(
            text(
                """
                select id
                from research_tasks
                where tenant_id = 1
                  and project_id = :project_a_id
                  and id = :task_a_id
                """
            ),
            {"project_a_id": PROJECT_A_ID, "task_a_id": RESEARCH_TASK_A_ID},
        )
        assert reachable_via_a == RESEARCH_TASK_A_ID

        # Tenant-only lookup also resolves Task A, proving the row exists.
        reachable_by_tenant_and_id = await session.scalar(
            text(
                """
                select id
                from research_tasks
                where tenant_id = 1
                  and id = :task_a_id
                """
            ),
            {"task_a_id": RESEARCH_TASK_A_ID},
        )
        assert reachable_by_tenant_and_id == RESEARCH_TASK_A_ID

        # Negative: project_id=B filter must hide Task A from Project B.
        selected = await session.scalar(
            text(
                """
                select id
                from research_tasks
                where tenant_id = 1
                  and project_id = :project_b_id
                  and id = :task_a_id
                """
            ),
            {"project_b_id": PROJECT_B_ID, "task_a_id": RESEARCH_TASK_A_ID},
        )

    assert selected is None


@pytest.mark.asyncio
async def test_research_tasks_cross_project_insert_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into research_tasks (
                      id, tenant_id, project_id, created_by_actor_id, title, status, metadata
                    )
                    values (
                      :task_a_id, 1, :project_b_id, :actor_id,
                      'Cross project duplicate task id', 'queued',
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {
                    "task_a_id": RESEARCH_TASK_A_ID,
                    "project_b_id": PROJECT_B_ID,
                    "actor_id": ACTOR_ID,
                },
            )
            await session.commit()

        assert _sqlstate(exc_info.value) == "23505"
        assert _constraint_name(exc_info.value) in {
            "research_tasks_pkey",
            "research_tasks_uq_tenant_id",
        }
        await session.rollback()


@pytest.mark.asyncio
async def test_research_tasks_cross_project_update_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Updating Task A must require Project A in the predicate.

    F-PR22-R2-006 P2 adopt: positive control (update via Project A
    succeeds) proves the row is reachable; the cross-project negative
    (update via Project B) then meaningfully verifies the project_id
    filter blocks the otherwise-reachable row.
    """

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

        # Positive control: update via Project A succeeds and changes title.
        updated_via_a = await session.scalar(
            text(
                """
                update research_tasks
                set title = 'Updated via Project A'
                where tenant_id = 1
                  and project_id = :project_a_id
                  and id = :task_a_id
                returning id
                """
            ),
            {"project_a_id": PROJECT_A_ID, "task_a_id": RESEARCH_TASK_A_ID},
        )
        assert updated_via_a == RESEARCH_TASK_A_ID

        # Negative: update predicate scoped to Project B must not match.
        updated = await session.scalar(
            text(
                """
                update research_tasks
                set title = 'Cross project update should not apply'
                where tenant_id = 1
                  and project_id = :project_b_id
                  and id = :task_a_id
                returning id
                """
            ),
            {"project_b_id": PROJECT_B_ID, "task_a_id": RESEARCH_TASK_A_ID},
        )
        title = await session.scalar(
            text(
                """
                select title
                from research_tasks
                where tenant_id = 1 and id = :task_a_id
                """
            ),
            {"task_a_id": RESEARCH_TASK_A_ID},
        )

    assert updated is None
    # Title reflects the positive control change, not the cross-project update.
    assert title == "Updated via Project A"


@pytest.mark.asyncio
async def test_research_tasks_cross_project_delete_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Deleting Task A must require Project A in the predicate.

    F-PR22-R2-006 P2 adopt: confirm Task A exists prior to the cross-
    project delete attempt so the post-condition (still_exists == 1)
    meaningfully shows the project_id filter prevented an otherwise
    successful delete. Without the existence proof, ``still_exists == 1``
    could also be satisfied by an absent row.
    """

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

        # Positive control: Task A exists prior to the negative attempt.
        pre_count = await session.scalar(
            text(
                """
                select count(*)
                from research_tasks
                where tenant_id = 1
                  and project_id = :project_a_id
                  and id = :task_a_id
                """
            ),
            {"project_a_id": PROJECT_A_ID, "task_a_id": RESEARCH_TASK_A_ID},
        )
        assert pre_count == 1

        # Negative: delete predicate scoped to Project B must not match.
        deleted = await session.scalar(
            text(
                """
                delete from research_tasks
                where tenant_id = 1
                  and project_id = :project_b_id
                  and id = :task_a_id
                returning id
                """
            ),
            {"project_b_id": PROJECT_B_ID, "task_a_id": RESEARCH_TASK_A_ID},
        )
        still_exists = await session.scalar(
            text(
                """
                select count(*)
                from research_tasks
                where tenant_id = 1 and id = :task_a_id
                """
            ),
            {"task_a_id": RESEARCH_TASK_A_ID},
        )

    assert deleted is None
    assert still_exists == 1
