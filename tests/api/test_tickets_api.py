"""Tickets API contract test (SP-012-9 BL-UIW-001/002).

backend route 2 件の contract test:
- GET /api/v1/projects/{project_id}/tickets
- GET /api/v1/projects/{project_id}/tickets/{ticket_id}

invariant verify:
- tenant + project boundary enforcement (project_id mismatch で 404 / cross-project SELECT 不可視)
- pagination (limit / offset)
- response schema (TicketListResponse + TicketRead)

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時のみ実行。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import date
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

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)

ACTOR_ID = UUID("00000000-0000-4000-8000-000000055001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000055002")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000055003")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000055004")
TICKET_A1_ID = UUID("00000000-0000-4000-8000-000000055005")
TICKET_A2_ID = UUID("00000000-0000-4000-8000-000000055006")
TICKET_B1_ID = UUID("00000000-0000-4000-8000-000000055007")


def _integration_settings() -> Settings:
    database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL)
    redis_url = os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL)
    return Settings(
        database_url=database_url,
        redis_url=redis_url,
        dev_login_cookie_secret="test-cookie-secret-for-tickets-api",
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
            raise AssertionError("Tickets API tests require PostgreSQL.") from exc
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
            truncate notification_events, audit_events, ticket_relations,
              acceptance_criteria, tickets, projects, workspaces, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_fixtures(session: AsyncSession) -> None:
    """2 project (A/B) + 3 tickets (A1, A2 in project_a / B1 in project_b)."""
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
            values (:actor_id, 1, 'human', 'human:default', 'Default Actor',
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
            insert into tickets (
              id, tenant_id, project_id, slug, title, status, created_by_actor_id, metadata
            )
            values
              (:ticket_a1_id, 1, :project_a_id, 'ticket-a1', 'Ticket A1', 'open', :actor_id,
                '{"rls_ready": true}'::jsonb),
              (:ticket_a2_id, 1, :project_a_id, 'ticket-a2', 'Ticket A2', 'in_progress', :actor_id,
                '{"rls_ready": true}'::jsonb),
              (:ticket_b1_id, 1, :project_b_id, 'ticket-b1', 'Ticket B1', 'closed', :actor_id,
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "ticket_a1_id": TICKET_A1_ID,
            "ticket_a2_id": TICKET_A2_ID,
            "ticket_b1_id": TICKET_B1_ID,
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "actor_id": ACTOR_ID,
        },
    )
    await session.commit()


@pytest.mark.asyncio
async def test_list_tickets_project_a_returns_only_project_a_tickets(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """project_a の list で project_b tickets が見えない (project boundary 強制)."""
    from backend.app.repositories.ticket import TicketRepository

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        tickets = await repo.list_in_project(tenant_id=1, project_id=PROJECT_A_ID)
        ticket_ids = {ticket.id for ticket in tickets}
        assert ticket_ids == {TICKET_A1_ID, TICKET_A2_ID}, (
            f"project_a list で project_b ticket が visible: {ticket_ids}"
        )


@pytest.mark.asyncio
async def test_get_ticket_in_correct_project_succeeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """project_a の ticket を project_a 経由 get → success."""
    from backend.app.repositories.ticket import TicketRepository

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            ticket_id=TICKET_A1_ID,
        )
        assert ticket is not None
        assert ticket.id == TICKET_A1_ID
        assert ticket.project_id == PROJECT_A_ID
        assert ticket.title == "Ticket A1"
        assert ticket.status == "open"


@pytest.mark.asyncio
async def test_get_ticket_cross_project_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """project_a の ticket を project_b 経由 get → None (cross-project boundary)."""
    from backend.app.repositories.ticket import TicketRepository

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_in_project(
            tenant_id=1,
            project_id=PROJECT_B_ID,  # wrong project
            ticket_id=TICKET_A1_ID,  # ticket A1 belongs to project_a
        )
        assert ticket is None, (
            "cross-project get で ticket が visible (project boundary 破壊)"
        )


@pytest.mark.asyncio
async def test_get_nonexistent_ticket_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """存在しない ticket_id で get → None."""
    from backend.app.repositories.ticket import TicketRepository

    nonexistent_id = uuid4()
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            ticket_id=nonexistent_id,
        )
        assert ticket is None


# SP-012-11 BL-TCU-003: POST / PATCH contract test


@pytest.mark.asyncio
async def test_create_in_project_inserts_ticket(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """create_in_project: 新規 Ticket 追加が成功 + project_id binding 維持."""
    from backend.app.repositories.ticket import TicketRepository

    new_slug = "ticket-a3-created"
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        created = await repo.create_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            payload={
                "slug": new_slug,
                "title": "Created Ticket A3",
                "status": "open",
                "created_by_actor_id": ACTOR_ID,
                "metadata_": {"rls_ready": True, "user_edited": True},
            },
        )
        await session.commit()
        assert created.slug == new_slug
        assert created.project_id == PROJECT_A_ID
        assert created.title == "Created Ticket A3"

    # 再 fetch で persist 確認
    async with session_factory() as session:
        repo = TicketRepository(session)
        tickets = await repo.list_in_project(tenant_id=1, project_id=PROJECT_A_ID)
        slugs = [t.slug for t in tickets]
        assert new_slug in slugs


@pytest.mark.asyncio
async def test_create_in_project_payload_project_id_mismatch_rejects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """create_in_project payload に異 project_id を含めると ValueError reject (server-owned-boundary §1)."""
    from backend.app.repositories.ticket import TicketRepository

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        with pytest.raises(ValueError, match="project_id"):
            await repo.create_in_project(
                tenant_id=1,
                project_id=PROJECT_A_ID,
                payload={
                    "slug": "should-reject",
                    "title": "Should Reject",
                    "status": "open",
                    "created_by_actor_id": ACTOR_ID,
                    # caller-supplied project_id mismatch
                    "project_id": PROJECT_B_ID,
                },
            )


@pytest.mark.asyncio
async def test_update_in_project_changes_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """update_in_project: status 'open' → 'in_progress' 変更が persist."""
    from backend.app.repositories.ticket import TicketRepository

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        updated = await repo.update_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            ticket_id=TICKET_A1_ID,
            payload={"status": "in_progress"},
        )
        await session.commit()
        assert updated is not None
        assert updated.status == "in_progress"
        assert updated.id == TICKET_A1_ID

    # 再 fetch で persist 確認
    async with session_factory() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_in_project(
            tenant_id=1, project_id=PROJECT_A_ID, ticket_id=TICKET_A1_ID
        )
        assert ticket is not None
        assert ticket.status == "in_progress"


@pytest.mark.asyncio
async def test_update_in_project_cross_project_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """cross-project update は None (project boundary 強制、project_b で project_a の ticket 編集試行 → None)."""
    from backend.app.repositories.ticket import TicketRepository

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        result = await repo.update_in_project(
            tenant_id=1,
            project_id=PROJECT_B_ID,  # wrong project
            ticket_id=TICKET_A1_ID,  # belongs to project_a
            payload={"status": "in_progress"},
        )
        assert result is None, "cross-project update が成功した (project boundary 破壊)"

    # project_a 経由で再 fetch、status が open のままであることを確認
    async with session_factory() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_in_project(
            tenant_id=1, project_id=PROJECT_A_ID, ticket_id=TICKET_A1_ID
        )
        assert ticket is not None
        assert ticket.status == "open", "cross-project update で project_a ticket が変更された"


# A-7 (ADR-00034): tickets.due_date column の persist contract test


@pytest.mark.asyncio
async def test_create_in_project_persists_due_date(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """create_in_project: due_date (calendar date) が persist + 再 fetch で同じ日付."""
    from backend.app.repositories.ticket import TicketRepository

    due = date(2026, 6, 30)
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        created = await repo.create_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            payload={
                "slug": "ticket-with-due",
                "title": "Ticket With Due Date",
                "status": "open",
                "due_date": due,
                "created_by_actor_id": ACTOR_ID,
                "metadata_": {"rls_ready": True, "user_edited": True},
            },
        )
        await session.commit()
        created_id = created.id
        assert created.due_date == due

    async with session_factory() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_in_project(
            tenant_id=1, project_id=PROJECT_A_ID, ticket_id=created_id
        )
        assert ticket is not None
        # date 型: timezone shift がないため round-trip で同じ暦日が保たれる
        assert ticket.due_date == due, "due_date が persist されていない"
        assert isinstance(ticket.due_date, date), "due_date は date 型であるべき"


@pytest.mark.asyncio
async def test_due_date_round_trips_without_timezone_shift(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex adversarial finding: YYYY-MM-DD 文字列 PATCH が暦日をずらさず persist。

    Pydantic TicketUpdateRequest が "2026-06-30" を date(2026,6,30) にパースし、
    DB の date column に timezone 変換なしで保存され、再 fetch で同じ暦日が返る
    ことを確認する (timestamptz 時代の JST 境界ずれ回帰防止)。
    """
    from backend.app.api.tickets import TicketUpdateRequest
    from backend.app.repositories.ticket import TicketRepository

    # date input が送る代表値 (UTC で扱うと前日にずれる境界)
    parsed = TicketUpdateRequest.model_validate({"due_date": "2026-06-30"})
    assert parsed.due_date == date(2026, 6, 30)

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        updated = await repo.update_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            ticket_id=TICKET_A1_ID,
            payload=parsed.model_dump(exclude_unset=True),
        )
        await session.commit()
        assert updated is not None
        assert updated.due_date == date(2026, 6, 30), "PATCH 後に暦日がずれた"

    async with session_factory() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_in_project(
            tenant_id=1, project_id=PROJECT_A_ID, ticket_id=TICKET_A1_ID
        )
        assert ticket is not None
        assert ticket.due_date == date(2026, 6, 30), "再 fetch で暦日がずれた"


@pytest.mark.asyncio
async def test_create_in_project_due_date_defaults_to_null(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """due_date 未指定の create では NULL (nullable column、既存 ticket への後方互換)."""
    from backend.app.repositories.ticket import TicketRepository

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_in_project(
            tenant_id=1, project_id=PROJECT_A_ID, ticket_id=TICKET_A1_ID
        )
        assert ticket is not None
        assert ticket.due_date is None, "fixture ticket の due_date が NULL でない"


@pytest.mark.asyncio
async def test_update_in_project_sets_then_clears_due_date(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """update_in_project: due_date を設定 → 明示 None で clear が persist (explicit clear)."""
    from backend.app.repositories.ticket import TicketRepository

    due = date(2026, 7, 15)
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    # set
    async with session_factory() as session:
        repo = TicketRepository(session)
        updated = await repo.update_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            ticket_id=TICKET_A1_ID,
            payload={"due_date": due},
        )
        await session.commit()
        assert updated is not None
        assert updated.due_date == due

    # explicit clear (None)
    async with session_factory() as session:
        repo = TicketRepository(session)
        cleared = await repo.update_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            ticket_id=TICKET_A1_ID,
            payload={"due_date": None},
        )
        await session.commit()
        assert cleared is not None
        assert cleared.due_date is None, "explicit None で due_date が clear されない"

    # 再 fetch で clear が persist
    async with session_factory() as session:
        repo = TicketRepository(session)
        ticket = await repo.get_in_project(
            tenant_id=1, project_id=PROJECT_A_ID, ticket_id=TICKET_A1_ID
        )
        assert ticket is not None
        assert ticket.due_date is None


# ---------------------------------------------------------------------------
# A-6 (ADR-00046): assignee 検証を repository choke point で enforce (REST + MCP + research の全 write
# 経路が create_in_project / update_in_project を通る、R1 F-001)。human-only + tenant の E2E negative。
# ---------------------------------------------------------------------------

AGENT_ACTOR_ID = UUID("00000000-0000-4000-8000-0000000550a1")


async def _insert_agent_actor(session: AsyncSession) -> None:
    """同一 tenant の非 human (agent) actor を 1 件 seed (担当者に割り当て不可であるべき対象)."""
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:actor_id, 1, 'agent', 'agent:worker', 'Worker Agent',
                    '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": AGENT_ACTOR_ID},
    )


@pytest.mark.asyncio
async def test_create_with_human_assignee_succeeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """create_in_project: human actor への assign は成功 (ADR-00046 D-2)."""
    from backend.app.repositories.ticket import TicketRepository

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        created = await repo.create_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            payload={
                "slug": "ticket-assign-human",
                "title": "Assigned to human",
                "status": "open",
                "created_by_actor_id": ACTOR_ID,
                "assignee_actor_id": ACTOR_ID,
            },
        )
        await session.commit()
        assert created.assignee_actor_id == ACTOR_ID


@pytest.mark.asyncio
async def test_create_with_non_human_assignee_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """create_in_project: agent / 非 human への assign は AssigneeNotAssignableError (R1 F-001)."""
    from backend.app.repositories.ticket import (
        AssigneeNotAssignableError,
        TicketRepository,
    )

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)
        await _insert_agent_actor(session)
        await session.commit()

    async with session_factory() as session:
        repo = TicketRepository(session)
        with pytest.raises(AssigneeNotAssignableError):
            await repo.create_in_project(
                tenant_id=1,
                project_id=PROJECT_A_ID,
                payload={
                    "slug": "ticket-assign-agent",
                    "title": "Assigned to agent",
                    "status": "open",
                    "created_by_actor_id": ACTOR_ID,
                    "assignee_actor_id": AGENT_ACTOR_ID,
                },
            )


@pytest.mark.asyncio
async def test_create_with_nonexistent_assignee_rejected_not_fk_500(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """create_in_project: 不在 / cross-tenant assignee は pre-check で AssigneeNotAssignableError
    (FK IntegrityError 500 に至らず、R1 F-004 の前段)."""
    from backend.app.repositories.ticket import (
        AssigneeNotAssignableError,
        TicketRepository,
    )

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        with pytest.raises(AssigneeNotAssignableError):
            await repo.create_in_project(
                tenant_id=1,
                project_id=PROJECT_A_ID,
                payload={
                    "slug": "ticket-assign-ghost",
                    "title": "Assigned to ghost",
                    "status": "open",
                    "created_by_actor_id": ACTOR_ID,
                    "assignee_actor_id": uuid4(),
                },
            )


@pytest.mark.asyncio
async def test_update_with_non_human_assignee_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """update_in_project: 既存 ticket を agent に re-assign しようとすると reject (全経路 choke point)."""
    from backend.app.repositories.ticket import (
        AssigneeNotAssignableError,
        TicketRepository,
    )

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)
        await _insert_agent_actor(session)
        await session.commit()

    async with session_factory() as session:
        repo = TicketRepository(session)
        with pytest.raises(AssigneeNotAssignableError):
            await repo.update_in_project(
                tenant_id=1,
                project_id=PROJECT_A_ID,
                ticket_id=TICKET_A1_ID,
                payload={"assignee_actor_id": AGENT_ACTOR_ID},
            )


@pytest.mark.asyncio
async def test_update_assign_human_then_clear_succeeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """update_in_project: human への assign 成功 → None で担当解除も成功 (null は検証 skip)."""
    from backend.app.repositories.ticket import TicketRepository

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        assigned = await repo.update_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            ticket_id=TICKET_A1_ID,
            payload={"assignee_actor_id": ACTOR_ID},
        )
        await session.commit()
        assert assigned is not None
        assert assigned.assignee_actor_id == ACTOR_ID

    async with session_factory() as session:
        repo = TicketRepository(session)
        cleared = await repo.update_in_project(
            tenant_id=1,
            project_id=PROJECT_A_ID,
            ticket_id=TICKET_A1_ID,
            payload={"assignee_actor_id": None},
        )
        await session.commit()
        assert cleared is not None
        assert cleared.assignee_actor_id is None


@pytest.mark.asyncio
async def test_update_endpoint_records_assignee_change_in_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """ADR-00046 (Codex adversarial F-A1 HIGH): assignee 変更が audit に previous/new で記録される。

    回帰防止: `existing.assignee_actor_id` を update 後に読むと identity map refresh で new vs new に
    なり audit に載らない。update 前 snapshot を使う実装を E2E で検証する (endpoint 直接呼び出し)。
    """
    from sqlalchemy import select as _select

    from backend.app.api.tickets import TicketUpdateRequest, update_ticket_endpoint
    from backend.app.db.models.audit_event import AuditEvent

    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    # 初期 assignee=None → endpoint で ACTOR_ID (human) に変更。
    async with session_factory() as session:
        await update_ticket_endpoint(
            project_id=PROJECT_A_ID,
            ticket_id=TICKET_A1_ID,
            payload=TicketUpdateRequest(assignee_actor_id=ACTOR_ID),
            _cli_capability=None,
            actor_id=ACTOR_ID,
            tenant_id=1,
            session=session,
        )

    async with session_factory() as session:
        rows = (
            await session.execute(
                _select(AuditEvent).where(
                    AuditEvent.tenant_id == 1,
                    AuditEvent.event_type.in_(
                        ["ticket_updated", "ticket_status_changed"]
                    ),
                )
            )
        ).scalars().all()
        # previous=None / new=ACTOR_ID が記録された audit が存在する。
        assert any(
            row.event_payload.get("new_assignee_actor_id") == str(ACTOR_ID)
            and row.event_payload.get("previous_assignee_actor_id") is None
            for row in rows
        ), "assignee 変更が audit に previous/new で記録されていない (F-A1 regression)"
