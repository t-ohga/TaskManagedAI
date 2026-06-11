"""ADR-00049 (SP-034) MCP create idempotency の DB-backed contract test。

reservation-first の atomic 挙動 (winner/loser、replay、conflict、cross-actor、null-key、並行 race、
reservation 完了形) を実 PostgreSQL で固定する。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時のみ実行 (host では skip)。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.mcp_idempotency_key import McpIdempotencyKey
from backend.app.db.session import create_engine
from backend.app.mcp.api_bridge import bridge_run_create, bridge_ticket_create
from backend.app.repositories.ticket import TicketNotActionableError
from backend.app.seeds.initial import (
    DEFAULT_ACTOR_ID,
    DEFAULT_PROJECT_ID,
    DEFAULT_TENANT_ID,
    seed_initial,
)
from backend.app.services.mcp_idempotency import IdempotencyConflictError

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)

_SECOND_ACTOR_ID = UUID("00000000-0000-4000-8000-0000000000a2")


def _integration_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-mcp-idempotency",
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(_REPO_ROOT / "alembic.ini")), "head")
    finally:
        if previous is None:
            os.environ.pop("TASKMANAGEDAI_DATABASE_URL", None)
        else:
            os.environ["TASKMANAGEDAI_DATABASE_URL"] = previous
        get_settings.cache_clear()


async def _assert_database_available(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("mcp idempotency test requires PostgreSQL.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


async def _seed_second_actor(session: AsyncSession) -> None:
    """cross-actor test 用の 2 番目の human actor (tickets.created_by_actor_id の FK target)。"""
    await session.execute(
        text(
            "insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata) "
            "values (:id, :tenant_id, 'human', :stable, 'Second User', "
            "'{\"rls_ready\": true}'::jsonb) on conflict do nothing"
        ),
        {"id": _SECOND_ACTOR_ID, "tenant_id": DEFAULT_TENANT_ID, "stable": "human:second"},
    )
    await session.commit()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)

    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    # seed_initial は呼び出し側 commit 前提。begin() で確実に commit し、per-test に ticket/run/
    # idempotency_key を reset (test 間で ticket slug が蓄積し unique 衝突するのを防ぐ)。
    async with factory.begin() as session:
        await session.execute(
            text(
                "truncate tickets, agent_runs, mcp_idempotency_keys "
                "restart identity cascade"
            )
        )
        await seed_initial(session)
        await _seed_second_actor(session)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _create_ticket_for_run(factory: async_sessionmaker[AsyncSession]) -> str:
    async with factory() as session:
        result = await bridge_ticket_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            title="run-target",
        )
    return str(result["ticket_id"])


@pytest.mark.asyncio
async def test_ticket_create_replay_returns_same_ticket(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    key = f"ticket-{uuid4()}"
    async with session_factory() as session:
        first = await bridge_ticket_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            title="idem",
            description="d",
            idempotency_key=key,
        )
    async with session_factory() as session:
        second = await bridge_ticket_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            title="idem",
            description="d",
            idempotency_key=key,
        )
    # 同一 key 再送 → 同一 ticket、2 個目は作成されない。
    assert first["ticket_id"] == second["ticket_id"]
    assert second.get("idempotent_replay") is True

    async with session_factory() as session:
        count = await session.scalar(
            text("select count(*) from tickets where title = 'idem'")
        )
    assert count == 1


@pytest.mark.asyncio
async def test_ticket_create_conflict_on_different_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    key = f"conflict-{uuid4()}"
    async with session_factory() as session:
        await bridge_ticket_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            title="original",
            idempotency_key=key,
        )
    # 同一 key + 異なる payload (title) → conflict。
    async with session_factory() as session:
        with pytest.raises(IdempotencyConflictError):
            await bridge_ticket_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=DEFAULT_PROJECT_ID,
                title="tampered",
                idempotency_key=key,
            )


@pytest.mark.asyncio
async def test_ticket_create_cross_actor_distinct(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    key = f"cross-{uuid4()}"
    async with session_factory() as session:
        a = await bridge_ticket_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            title="actor-a",
            idempotency_key=key,
            actor_id=DEFAULT_ACTOR_ID,
        )
    async with session_factory() as session:
        b = await bridge_ticket_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            title="actor-b",
            idempotency_key=key,
            actor_id=_SECOND_ACTOR_ID,
        )
    # 別 actor は同 key でも互いに干渉せず別 ticket を得る。
    assert a["ticket_id"] != b["ticket_id"]
    assert b.get("idempotent_replay") is None


@pytest.mark.asyncio
async def test_ticket_create_null_key_creates_each_time(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        a = await bridge_ticket_create(
            session, tenant_id=DEFAULT_TENANT_ID, project_id=DEFAULT_PROJECT_ID, title="n"
        )
    async with session_factory() as session:
        b = await bridge_ticket_create(
            session, tenant_id=DEFAULT_TENANT_ID, project_id=DEFAULT_PROJECT_ID, title="n"
        )
    assert a["ticket_id"] != b["ticket_id"]


@pytest.mark.asyncio
async def test_concurrent_same_key_creates_one_ticket(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    key = f"race-{uuid4()}"

    async def _attempt() -> str:
        async with session_factory() as session:
            result = await bridge_ticket_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=DEFAULT_PROJECT_ID,
                title="race",
                idempotency_key=key,
            )
            return str(result["ticket_id"])

    ids = await asyncio.gather(_attempt(), _attempt())
    # 並行同一 key → 1 ticket のみ、両者同一 id。
    assert ids[0] == ids[1]
    async with session_factory() as session:
        reservation = await session.scalar(
            select(McpIdempotencyKey).where(
                McpIdempotencyKey.tenant_id == DEFAULT_TENANT_ID,
                McpIdempotencyKey.tool_name == "ticket_create",
                McpIdempotencyKey.idempotency_key == key,
            )
        )
    assert reservation is not None
    # reservation は completed (3 列 set、CHECK)。
    assert reservation.completed_at is not None
    assert reservation.created_resource_kind == "ticket"
    assert reservation.created_resource_id == UUID(ids[0])


@pytest.mark.asyncio
async def test_run_create_replay_returns_same_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ticket_id = await _create_ticket_for_run(session_factory)
    key = f"run-{uuid4()}"
    async with session_factory() as session:
        first = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="p",
            idempotency_key=key,
        )
    async with session_factory() as session:
        second = await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="p",
            idempotency_key=key,
        )
    assert first["run_id"] == second["run_id"]
    assert second.get("idempotent_replay") is True


@pytest.mark.asyncio
async def test_blank_idempotency_key_creates_each_time(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # ADR-00049 R3 F-O3: 空文字 / 空白のみ key は未指定とみなし毎回新規作成 (共有 bucket poisoning 防止)。
    for blank in ("", "   "):
        async with session_factory() as session:
            a = await bridge_ticket_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=DEFAULT_PROJECT_ID,
                title="blank",
                idempotency_key=blank,
            )
        async with session_factory() as session:
            b = await bridge_ticket_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=DEFAULT_PROJECT_ID,
                title="blank",
                idempotency_key=blank,
            )
        assert a["ticket_id"] != b["ticket_id"]
        assert a.get("idempotent_replay") is None


@pytest.mark.asyncio
async def test_run_create_replay_rejected_after_ticket_soft_delete(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # ADR-00049 R3 F-O4: soft-deleted ticket の run を idempotency replay で再露出しない。
    ticket_id = await _create_ticket_for_run(session_factory)
    key = f"run-sd-{uuid4()}"
    async with session_factory() as session:
        await bridge_run_create(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=ticket_id,
            purpose="p",
            idempotency_key=key,
        )
    async with session_factory() as session:
        await session.execute(
            text("update tickets set deleted_at = now() where id = :id"),
            {"id": UUID(ticket_id)},
        )
        await session.commit()
    # ticket soft-delete 後の replay は active-scope 再検証で reject される (bridge 直呼びは raise)。
    async with session_factory() as session:
        with pytest.raises(TicketNotActionableError):
            await bridge_run_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=DEFAULT_PROJECT_ID,
                ticket_id=ticket_id,
                purpose="p",
                idempotency_key=key,
            )


@pytest.mark.asyncio
async def test_run_create_idempotency_key_with_commit_false_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ticket_id = await _create_ticket_for_run(session_factory)
    async with session_factory() as session:
        with pytest.raises(ValueError, match="commit=False"):
            await bridge_run_create(
                session,
                tenant_id=DEFAULT_TENANT_ID,
                project_id=DEFAULT_PROJECT_ID,
                ticket_id=ticket_id,
                purpose="p",
                commit=False,
                idempotency_key=f"bad-{uuid4()}",
            )
