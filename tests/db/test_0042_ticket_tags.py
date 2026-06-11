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
        # confdeltype は pg "char" 型で asyncpg は bytes (b'r') を返すため decode して比較する。
        actions = {r[0]: (r[1].decode() if isinstance(r[1], bytes) else r[1]) for r in rows}
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
            "insert into workspaces (id, tenant_id, slug, name, owner_actor_id) "
            "values (:id, 1, :slug, :name, '00000000-0000-4000-8000-00000000b001')"
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
                "insert into actors (id, tenant_id, actor_type, actor_id, display_name) "
                "values (:id, 1, 'human', :actor_handle, 'seed')"
            ),
            {"id": actor_id, "actor_handle": f"human:seed-{actor_id[:8]}"},
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
async def test_ticket_ids_with_tag_rejects_cross_project(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """filter primitive も repository boundary で fail-closed (R6 HIGH)。

    ``ticket_ids_with_tag`` を project A scope で project B の tag に対して呼ぶと、
    空 list でなく ``TagNotFoundError`` を raise する (direct repository caller が
    cross-project tag を「該当 0 件」と取り違えない)。
    """
    from uuid import UUID

    from backend.app.repositories.tag import TagNotFoundError, TagRepository

    project_a, project_b, tag_b = str(uuid4()), str(uuid4()), str(uuid4())
    async with session_factory() as session:
        await _seed_project_ticket_tag(session, project_id=project_a, ticket_id=None, tag_id=None)
        await _seed_project_ticket_tag(session, project_id=project_b, ticket_id=None, tag_id=tag_b)
        repo = TagRepository(session)
        with pytest.raises(TagNotFoundError):
            await repo.ticket_ids_with_tag(1, UUID(project_a), UUID(tag_b))


@pytest.mark.asyncio
async def test_ticket_ids_with_tag_excludes_soft_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """filter primitive は soft-deleted ticket を除外する (R7 HIGH)。

    tag を付与した ticket を soft-delete (deleted_at セット) すると、ticket_tags 行は残るが
    ``ticket_ids_with_tag`` は active ticket join + deleted_at IS NULL で除外する。direct caller が
    削除済 ticket を tag 経由で取り戻せない。
    """
    from uuid import UUID

    from backend.app.repositories.tag import TagRepository

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
        repo = TagRepository(session)
        active = await repo.ticket_ids_with_tag(1, UUID(project_id), UUID(tag_id))
        assert UUID(ticket_id) in active
        # soft-delete (deletion batch model: deleted_at セット、join row は残る)
        await session.execute(
            text("update tickets set deleted_at = now() where id = :id"),
            {"id": ticket_id},
        )
        await session.flush()
        after_delete = await repo.ticket_ids_with_tag(1, UUID(project_id), UUID(tag_id))
        assert UUID(ticket_id) not in after_delete


@pytest.mark.asyncio
async def test_tags_for_tickets_excludes_soft_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """bulk embed primitive も soft-deleted ticket を除外する (R8 HIGH)。

    tag を付与した ticket を soft-delete すると、``tags_for_tickets([ticket_id])`` は
    その ticket の entry を返さない (削除済 ticket の tag metadata を direct caller に渡さない)。
    """
    from uuid import UUID

    from backend.app.repositories.tag import TagRepository

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
        repo = TagRepository(session)
        active = await repo.tags_for_tickets(1, UUID(project_id), [UUID(ticket_id)])
        assert UUID(ticket_id) in active
        await session.execute(
            text("update tickets set deleted_at = now() where id = :id"),
            {"id": ticket_id},
        )
        await session.flush()
        after_delete = await repo.tags_for_tickets(1, UUID(project_id), [UUID(ticket_id)])
        assert UUID(ticket_id) not in after_delete


@pytest.mark.asyncio
async def test_ticket_read_with_tags_helper_injects_after_update(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """PATCH/POST 用の共通 helper ``_ticket_read_with_tags`` が更新後 ticket にも tag を注入する
    (Codex R9 HIGH: 更新応答が tag 付き ticket を「タグなし」と誤認させない)。

    tag を attach した ticket を title 更新した後、helper が返す TicketRead.tags に tag が残る。
    """
    from uuid import UUID

    from backend.app.api.tickets import _ticket_read_with_tags
    from backend.app.repositories.tag import TagRepository
    from backend.app.repositories.ticket import TicketRepository

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
        # title を更新 (PATCH 相当)
        await session.execute(
            text("update tickets set title = 'updated' where id = :id"),
            {"id": ticket_id},
        )
        await session.flush()
        ticket = await TicketRepository(session).get_in_project(
            tenant_id=1, project_id=UUID(project_id), ticket_id=UUID(ticket_id)
        )
        assert ticket is not None
        read = await _ticket_read_with_tags(session, 1, UUID(project_id), ticket)
        # 更新後でも tag が応答に残る
        assert {str(t.id) for t in read.tags} == {tag_id}
        # 参考: 注入しない素の TicketRead は tags=[] (helper が必要な理由)
        bare = await TagRepository(session).tags_for_tickets(
            1, UUID(project_id), [UUID(ticket_id)]
        )
        assert UUID(ticket_id) in bare


@pytest.mark.asyncio
async def test_create_and_attach_is_atomic(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """create_and_attach_tag は ticket actionable を先に検証し、不在 ticket なら tag を作らない
    (atomic、Codex R5 HIGH: 部分成功の孤立 tag を防ぐ)。"""
    from uuid import UUID

    from backend.app.repositories.tag import TagRepository
    from backend.app.repositories.ticket import TicketNotActionableError

    project_id, ticket_id = str(uuid4()), str(uuid4())
    missing_ticket = str(uuid4())
    async with session_factory() as session:
        await _seed_project_ticket_tag(
            session, project_id=project_id, ticket_id=ticket_id, tag_id=None
        )
        repo = TagRepository(session)
        # 不在 ticket への create+attach → ticket actionable 検証で弾かれ tag は作られない
        with pytest.raises(TicketNotActionableError):
            await repo.create_and_attach_tag(
                1, UUID(project_id), UUID(missing_ticket), name="orphan", color="red"
            )
        # 孤立 tag が作られていないこと (atomic)
        leaked = await session.scalar(
            text("select count(*) from tags where project_id = :pid and name = 'orphan'"),
            {"pid": project_id},
        )
        assert leaked == 0
        # 正常系: actionable ticket への create+attach は tag 作成 + 付与の両方を残す
        tag = await repo.create_and_attach_tag(
            1, UUID(project_id), UUID(ticket_id), name="bug", color="blue"
        )
        await session.flush()
        attached = await session.scalar(
            text(
                "select count(*) from ticket_tags where ticket_id = :tid and tag_id = :tag"
            ),
            {"tid": ticket_id, "tag": str(tag.id)},
        )
        assert attached == 1


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
async def test_delete_tag_in_use_is_active_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """delete_tag の使用中判定は active ticket のみで数える (R9 HIGH)。

    - active ticket への付与がある → TagInUseError (409、attached_count は active 件数)
    - その ticket を soft-delete し active 0 件 → tag は削除可能 (deleted 付与は内部 cleanup)
    - 削除後 tag は存在せず、deleted ticket の ticket_tags も cleanup 済 (restore で tag 復活しない)
    """
    from uuid import UUID

    from backend.app.repositories.tag import TagInUseError, TagRepository

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
        repo = TagRepository(session)
        # active ticket に付与中 → 削除不可 (使用中ガードは select のみで raise、session は dirty でない)
        with pytest.raises(TagInUseError) as excinfo:
            await repo.delete_tag(1, UUID(project_id), UUID(tag_id), actor_id=None)
        assert excinfo.value.attached_count == 1
        # soft-delete ticket → active 0 件 → 削除可能 (deleted 付与は内部 cleanup)
        await session.execute(
            text("update tickets set deleted_at = now() where id = :id"),
            {"id": ticket_id},
        )
        await session.flush()
        await repo.delete_tag(1, UUID(project_id), UUID(tag_id), actor_id=None)
        await session.flush()
        # tag は hard-delete 済 + deleted ticket の ticket_tags も cleanup 済
        assert await repo.get_tag(1, UUID(project_id), UUID(tag_id)) is None
        remaining = await session.scalar(
            text("select count(*) from ticket_tags where tag_id = :tag"), {"tag": tag_id}
        )
        assert remaining == 0


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
