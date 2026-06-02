"""ADR-00044 (A-5) migration 0042 の DB contract test (Codex code-review R2 HIGH-2)。

実 migrated PostgreSQL schema を introspect し、ORM metadata test では検証できない以下を固定する:
- ticket_tags の FK2 (tag) が ON DELETE RESTRICT (pg_constraint.confdeltype='r')、FK1 (ticket) が CASCADE
- 両 FK が (tenant_id, project_id) を共有 (同一 project 強制)
- tags の project内name unique / FK target unique / name長・color CHECK
- **raw negatives**: cross-project な ticket_tags insert は複合 FK で拒否 / 使用中 tag の raw delete は
  FK2 RESTRICT で拒否

`TASKMANAGEDAI_RUN_DB_TESTS=1` + test PostgreSQL でのみ実行 (host dev では skip)。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATABASE_URL = "postgresql+asyncpg://taskmanagedai:test-password@localhost:5434/taskmanagedai"
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"

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
        dev_login_cookie_secret="test-cookie-secret-for-0042-ticket-tags",
    )


def _run_alembic(
    database_url: str, direction: Literal["upgrade", "downgrade"], target: str
) -> None:
    previous = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        if direction == "upgrade":
            command.upgrade(config, target)
        else:
            command.downgrade(config, target)
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
            raise AssertionError("0042 ticket tag tests require PostgreSQL.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
        await engine.dispose()


# ── 実 migrated schema の pg_constraint introspection (seed 不要) ──


@pytest.mark.asyncio
async def test_ticket_tags_fk_delete_actions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FK2 (tag) は RESTRICT (confdeltype='r')、FK1 (ticket) は CASCADE ('c')。"""
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "select conname, confdeltype from pg_constraint "
                "where conrelid = 'ticket_tags'::regclass and contype = 'f'"
            )
        )
        actions = {r[0]: r[1] for r in rows}
    assert actions["ticket_tags_tag_fkey"] == "r"  # RESTRICT (使用中 tag 削除を DB で拒否)
    assert actions["ticket_tags_ticket_fkey"] == "c"  # CASCADE


@pytest.mark.asyncio
async def test_tags_constraints_in_postgres(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """tags の unique / CHECK が実 DB に存在する。"""
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "select conname, contype from pg_constraint "
                "where conrelid = 'tags'::regclass"
            )
        )
        names = {r[0] for r in rows}
    assert "tags_uq_tenant_project_name" in names
    assert "tags_uq_tenant_project_id" in names
    assert "tags_ck_name_length" in names
    assert "tags_ck_color" in names


# ── raw negatives ──


async def _seed_project_ticket_tag(
    session: AsyncSession, *, project_id: str, ticket_id: str | None, tag_id: str | None
) -> None:
    """tenant_id=1 配下に最小の project (+ 任意で ticket / tag) を seed する。"""
    workspace_id = str(uuid4())
    await session.execute(
        text(
            "insert into workspaces (id, tenant_id, slug, name) "
            "values (:id, 1, :slug, :name)"
        ),
        {"id": workspace_id, "slug": f"ws-{workspace_id[:8]}", "name": "ws"},
    )
    await session.execute(
        text(
            "insert into projects (id, tenant_id, workspace_id, slug, name, status) "
            "values (:id, 1, :ws, :slug, :name, 'active')"
        ),
        {"id": project_id, "ws": workspace_id, "slug": f"p-{project_id[:8]}", "name": "p"},
    )
    if ticket_id is not None:
        actor_id = str(uuid4())
        await session.execute(
            text(
                "insert into actors (id, tenant_id, actor_type, display_name) "
                "values (:id, 1, 'human', 'seed')"
            ),
            {"id": actor_id},
        )
        await session.execute(
            text(
                "insert into tickets (id, tenant_id, project_id, slug, title, status, "
                "created_by_actor_id) values (:id, 1, :pid, :slug, 't', 'open', :actor)"
            ),
            {"id": ticket_id, "pid": project_id, "slug": f"t-{ticket_id[:8]}", "actor": actor_id},
        )
    if tag_id is not None:
        await session.execute(
            text(
                "insert into tags (id, tenant_id, project_id, name, color) "
                "values (:id, 1, :pid, :name, 'red')"
            ),
            {"id": tag_id, "pid": project_id, "name": f"tag-{tag_id[:8]}"},
        )
    await session.flush()


@pytest.mark.asyncio
async def test_cross_project_attach_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """project A の ticket に project B の tag を付与する raw insert は複合 FK で拒否される。"""
    project_a, project_b = str(uuid4()), str(uuid4())
    ticket_a, tag_b = str(uuid4()), str(uuid4())
    async with session_factory() as session:
        await _seed_project_ticket_tag(session, project_id=project_a, ticket_id=ticket_a, tag_id=None)
        await _seed_project_ticket_tag(session, project_id=project_b, ticket_id=None, tag_id=tag_b)
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "insert into ticket_tags (tenant_id, project_id, ticket_id, tag_id) "
                    "values (1, :pid, :tid, :tag)"
                ),
                {"pid": project_a, "tid": ticket_a, "tag": tag_b},
            )
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_get_tag_rejects_cross_project_tag(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """tag filter の fail-closed 検証元: project A scope で project B の tag を get_tag すると None
    (endpoint は 404 に倒す、Codex R4 HIGH)。同 project では取得できる。"""
    from uuid import UUID

    from backend.app.repositories.tag import TagRepository

    project_a, project_b, tag_b = str(uuid4()), str(uuid4()), str(uuid4())
    async with session_factory() as session:
        await _seed_project_ticket_tag(session, project_id=project_a, ticket_id=None, tag_id=None)
        await _seed_project_ticket_tag(session, project_id=project_b, ticket_id=None, tag_id=tag_b)
        repo = TagRepository(session)
        assert await repo.get_tag(1, UUID(project_a), UUID(tag_b)) is None
        assert await repo.get_tag(1, UUID(project_b), UUID(tag_b)) is not None


@pytest.mark.asyncio
async def test_detach_rejects_cross_project_tag(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """detach も attach と対称に cross-project tag を 404 fail-closed する (R5 HIGH)。

    project A の ticket に対し project B の tag_id を detach すると、0 rows no-op で
    隠さず ``TagNotFoundError`` (→ endpoint 404) を raise する。
    """
    from uuid import UUID

    from backend.app.repositories.tag import TagNotFoundError, TagRepository

    project_a, ticket_a = str(uuid4()), str(uuid4())
    project_b, tag_b = str(uuid4()), str(uuid4())
    async with session_factory() as session:
        await _seed_project_ticket_tag(
            session, project_id=project_a, ticket_id=ticket_a, tag_id=None
        )
        await _seed_project_ticket_tag(session, project_id=project_b, ticket_id=None, tag_id=tag_b)
        repo = TagRepository(session)
        with pytest.raises(TagNotFoundError):
            await repo.detach_tag(1, UUID(project_a), UUID(ticket_a), UUID(tag_b))


@pytest.mark.asyncio
async def test_raw_delete_of_attached_tag_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """使用中 (ticket_tags 有) tag の raw delete は FK2 RESTRICT で拒否される。"""
    project_id, ticket_id, tag_id = str(uuid4()), str(uuid4()), str(uuid4())
    async with session_factory() as session:
        await _seed_project_ticket_tag(
            session, project_id=project_id, ticket_id=ticket_id, tag_id=tag_id
        )
        await session.execute(
            text(
                "insert into ticket_tags (tenant_id, project_id, ticket_id, tag_id) "
                "values (1, :pid, :tid, :tag)"
            ),
            {"pid": project_id, "tid": ticket_id, "tag": tag_id},
        )
        await session.flush()
        with pytest.raises(IntegrityError):
            await session.execute(
                text("delete from tags where id = :id"), {"id": tag_id}
            )
            await session.flush()
        await session.rollback()
