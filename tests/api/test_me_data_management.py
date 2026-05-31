"""Q-2〜Q-4 (ADR-00037) data management contract test.

破壊的データ管理 3 機能の contract / negative test:

- Q-4: project archive/unarchive (CAS + audit + owner gate + child-write 凍結)
- Q-3: ticket 一括 soft-delete + batch restore (active scope / batch 限定 / idempotent / audit)
- Q-2: ticket 一括 import (all-or-nothing / slug 衝突 reject / dry-run / DB unique 最終防衛)

ADR-00037 §テスト指針 + DoD を網羅。fast (no DB) schema / guard test と DB-backed test (owner gate /
archived freeze 全経路 / cross-tenant / cross-project negative) に分ける。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時のみ実行。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.api.me import (
    BulkSoftDeleteRequest,
    ImportTicketsRequest,
    ProjectArchiveUpdate,
    RestoreBatchRequest,
    bulk_soft_delete_tickets_endpoint,
    import_tickets_endpoint,
    require_project_owner,
    restore_tickets_batch_endpoint,
    update_project_archive_endpoint,
)
from backend.app.config import Settings, get_settings
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.session import create_engine
from backend.app.mcp.api_bridge import (
    bridge_approval_list,
    bridge_approval_request_create,
    bridge_approval_show,
    bridge_delegation_accept,
    bridge_delegation_create,
    bridge_delegation_inbox,
    bridge_delegation_review,
    bridge_delegation_submit,
    bridge_delegation_tree,
    bridge_run_cost,
    bridge_run_create,
    bridge_run_list,
    bridge_run_show,
    bridge_run_update,
    bridge_ticket_comment,
    bridge_ticket_create,
    bridge_ticket_list_all,
    bridge_ticket_search,
    bridge_workflow_status,
)
from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID
from backend.app.repositories.ticket import (
    BulkDeleteCountMismatch,
    ProjectArchivedError,
    TicketNotActionableError,
    TicketRepository,
)
from backend.app.schemas.ticket import TicketImportItem
from backend.app.services.policy.archive_settings import (
    ArchiveExpectationMismatch,
    ProjectArchiveService,
)

# --------- 共通 ID ---------

TENANT_1 = 1
TENANT_2 = 2

ACTOR_OWNER = UUID("00000000-0000-4000-8000-0000000dd001")
ACTOR_EXTRA_HUMAN = UUID("00000000-0000-4000-8000-0000000dd002")
ACTOR_SERVICE = UUID("00000000-0000-4000-8000-0000000dd003")
ACTOR_AGENT = UUID("00000000-0000-4000-8000-0000000dd004")
ACTOR_PROVIDER = UUID("00000000-0000-4000-8000-0000000dd005")
ACTOR_GITHUB_APP = UUID("00000000-0000-4000-8000-0000000dd006")
ACTOR_OWNER_T2 = UUID("00000000-0000-4000-8000-0000000dd007")

WORKSPACE_1 = UUID("00000000-0000-4000-8000-0000000dd010")
WORKSPACE_2 = UUID("00000000-0000-4000-8000-0000000dd011")

PROJECT_ACTIVE = UUID("00000000-0000-4000-8000-0000000dd020")
PROJECT_OTHER = UUID("00000000-0000-4000-8000-0000000dd021")
PROJECT_ARCHIVED = UUID("00000000-0000-4000-8000-0000000dd022")
PROJECT_T2 = UUID("00000000-0000-4000-8000-0000000dd023")

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_OWNER_STABLE_ID = "human:default"


# --------- fake request (owner gate) ---------


def _fake_request(*, authenticated: bool) -> object:
    """owner gate が参照する request.state.authenticated と
    request.app.state.settings.default_actor_id を持つ最小 fake request。
    """
    return SimpleNamespace(
        state=SimpleNamespace(authenticated=authenticated),
        app=SimpleNamespace(
            state=SimpleNamespace(settings=SimpleNamespace(default_actor_id=_OWNER_STABLE_ID))
        ),
    )


# =========================================================================
# fast (no DB): schema validation + repository guard
# =========================================================================


def test_ticket_import_item_forbids_server_owned_fields() -> None:
    """caller は slug/title/description/status/priority のみ指定でき、
    created_by_actor_id / tenant_id / project_id / metadata は注入経路 (extra=forbid)。
    """
    item = TicketImportItem(slug="abc-1", title="Title")
    assert item.status == "open"  # default
    assert item.priority is None
    # server-owned field を caller が渡そうとすると reject
    for forbidden in ("created_by_actor_id", "tenant_id", "project_id", "metadata", "id"):
        with pytest.raises(ValidationError):
            TicketImportItem(slug="abc-2", title="t", **{forbidden: "x"})


def test_ticket_import_item_rejects_invalid_slug() -> None:
    for bad_slug in ("", "Abc", "abc_1", "a b", "-abc", "abc-"):
        with pytest.raises(ValidationError):
            TicketImportItem(slug=bad_slug, title="t")


def test_ticket_import_item_enforces_payload_size_bounds() -> None:
    """ADR-00037 DoD / Codex adversarial R8: import item の payload size 上限
    (slug/title/description の max_length)。件数上限に加えた untrusted boundary の size 防御。
    """
    from backend.app.schemas.ticket import (
        IMPORT_DESCRIPTION_MAX_LENGTH,
        IMPORT_SLUG_MAX_LENGTH,
        IMPORT_TITLE_MAX_LENGTH,
    )

    # 上限ちょうどは valid
    TicketImportItem(
        slug="a" * IMPORT_SLUG_MAX_LENGTH,
        title="t" * IMPORT_TITLE_MAX_LENGTH,
        description="d" * IMPORT_DESCRIPTION_MAX_LENGTH,
    )
    # 超過は ValidationError (slug / title / description それぞれ)
    with pytest.raises(ValidationError):
        TicketImportItem(slug="a" * (IMPORT_SLUG_MAX_LENGTH + 1), title="t")
    with pytest.raises(ValidationError):
        TicketImportItem(slug="ok", title="t" * (IMPORT_TITLE_MAX_LENGTH + 1))
    with pytest.raises(ValidationError):
        TicketImportItem(
            slug="ok",
            title="t",
            description="d" * (IMPORT_DESCRIPTION_MAX_LENGTH + 1),
        )


def test_import_request_enforces_count_bounds() -> None:
    """件数上限 100 + 下限 1 (ADR-00037 bounded)。"""
    items = [{"slug": f"t-{i}", "title": f"T{i}"} for i in range(100)]
    ok = ImportTicketsRequest(tickets=items)  # type: ignore[arg-type]
    assert len(ok.tickets) == 100
    # 0 件は reject
    with pytest.raises(ValidationError):
        ImportTicketsRequest(tickets=[])
    # 101 件は reject
    with pytest.raises(ValidationError):
        ImportTicketsRequest(tickets=[{"slug": f"t-{i}", "title": "T"} for i in range(101)])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_ticket_repository_create_is_forbidden() -> None:
    """archived guard を通らない base ``create`` は ticket では禁止 (ADR-00037 R5 #2)。

    get/list/update/delete と同じく ``create`` も NotImplementedError にし、全 caller を
    guard 済の ``create_in_project`` へ閉じる (MCP bridge 等の非 HTTP 経路の bypass を塞ぐ)。
    DB 不要: override は self.session を触らず即 raise する。
    """
    repo = TicketRepository(cast(Any, None))
    with pytest.raises(NotImplementedError, match="create_in_project"):
        await repo.create(TENANT_1, {"slug": "x", "title": "t"})


# =========================================================================
# DB-backed
# =========================================================================

pytestmark_db = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _integration_settings() -> Settings:
    database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL)
    redis_url = os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL)
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=database_url,
        redis_url=redis_url,
        dev_login_cookie_secret="test-cookie-secret-for-data-management",
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
            raise AssertionError("data management tests require PostgreSQL.") from exc
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


async def _seed_base(session: AsyncSession) -> None:
    """tenant 1 (owner + 5 非owner actor + active/other/archived project) +
    tenant 2 (owner + active project) を seed (tickets は各 test で個別 seed)。
    """
    await session.execute(
        text(
            "insert into tenants (id, name, metadata) values "
            "(1, 'tenant-one', '{\"rls_ready\": true}'::jsonb), "
            "(2, 'tenant-two', '{\"rls_ready\": true}'::jsonb)"
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values
              (:owner, 1, 'human', 'human:default', 'Owner One', '{"rls_ready": true}'::jsonb),
              (:exh, 1, 'human', 'human:other', 'Extra Human', '{"rls_ready": true}'::jsonb),
              (:svc, 1, 'service', 'service:worker1', 'Worker', '{"rls_ready": true}'::jsonb),
              (:agt, 1, 'agent', 'agent:runner1', 'Agent', '{"rls_ready": true}'::jsonb),
              (:prv, 1, 'provider', 'provider:openai', 'Provider', '{"rls_ready": true}'::jsonb),
              (:gha, 1, 'github_app', 'github_app:repo', 'GH App', '{"rls_ready": true}'::jsonb),
              (:super, 1, 'agent', 'agent:superintendent', 'Superintendent',
                '{"rls_ready": true}'::jsonb),
              (:o2, 2, 'human', 'human:default', 'Owner Two', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "owner": ACTOR_OWNER,
            "exh": ACTOR_EXTRA_HUMAN,
            "svc": ACTOR_SERVICE,
            "agt": ACTOR_AGENT,
            "prv": ACTOR_PROVIDER,
            "gha": ACTOR_GITHUB_APP,
            "super": DEFAULT_SUPERINTENDENT_ACTOR_ID,
            "o2": ACTOR_OWNER_T2,
        },
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values
              (:w1, 1, 'workspace', 'workspace', :owner, '{"rls_ready": true}'::jsonb),
              (:w2, 2, 'workspace2', 'workspace2', :o2, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"w1": WORKSPACE_1, "w2": WORKSPACE_2, "owner": ACTOR_OWNER, "o2": ACTOR_OWNER_T2},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:active, 1, :w1, 'project-active', 'active', 'active', '{"rls_ready": true}'::jsonb),
              (:other, 1, :w1, 'project-other', 'other', 'active', '{"rls_ready": true}'::jsonb),
              (:arch, 1, :w1, 'project-archived', 'arch', 'archived', '{"rls_ready": true}'::jsonb),
              (:t2, 2, :w2, 'project-t2', 't2', 'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "active": PROJECT_ACTIVE,
            "other": PROJECT_OTHER,
            "arch": PROJECT_ARCHIVED,
            "t2": PROJECT_T2,
            "w1": WORKSPACE_1,
            "w2": WORKSPACE_2,
        },
    )
    await session.commit()


async def _seed_tickets(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    slugs: list[str],
    created_by: UUID | None = None,
) -> None:
    # 複合 FK (tenant_id, created_by_actor_id) のため tenant に在籍する actor を使う。
    creator = created_by or (ACTOR_OWNER if tenant_id == TENANT_1 else ACTOR_OWNER_T2)
    repo = TicketRepository(session)
    for slug in slugs:
        await repo.create_in_project(
            tenant_id,
            project_id,
            {
                "slug": slug,
                "title": f"Title {slug}",
                "status": "open",
                "created_by_actor_id": creator,
                "metadata_": {"rls_ready": True},
            },
        )
    await session.commit()


async def _audit_events(session: AsyncSession, tenant_id: int) -> list[AuditEvent]:
    result = await session.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.created_at)
    )
    return list(result.scalars().all())


# --------- Q-4 archive ---------


@pytestmark_db
@pytest.mark.asyncio
async def test_archive_active_to_archived_changes_and_audits(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        item = await update_project_archive_endpoint(
            project_id=PROJECT_ACTIVE,
            payload=ProjectArchiveUpdate(archived=True, expected_status="active"),
            owner_actor_id=ACTOR_OWNER,
            tenant_id=TENANT_1,
            session=session,
        )
        assert item.status == "archived"

    async with session_factory() as session:
        status = await session.scalar(
            text("select status from projects where id = :p"), {"p": PROJECT_ACTIVE}
        )
        assert status == "archived"
        events = await _audit_events(session, TENANT_1)
        config_changed = [e for e in events if e.event_type == "config_changed"]
        assert len(config_changed) == 1
        payload = config_changed[0].event_payload
        assert payload["changed_fields"] == ["status"]
        assert payload["previous_status"] == "active"
        assert payload["new_status"] == "archived"
        assert config_changed[0].actor_id == ACTOR_OWNER


@pytestmark_db
@pytest.mark.asyncio
async def test_unarchive_archived_to_active(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        item = await update_project_archive_endpoint(
            project_id=PROJECT_ARCHIVED,
            payload=ProjectArchiveUpdate(archived=False, expected_status="archived"),
            owner_actor_id=ACTOR_OWNER,
            tenant_id=TENANT_1,
            session=session,
        )
        assert item.status == "active"


@pytestmark_db
@pytest.mark.asyncio
async def test_archive_cas_mismatch_returns_409(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """stale baseline (expected_status が現在と不一致) は 409 で reject (二重 archive 防止)。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await update_project_archive_endpoint(
                project_id=PROJECT_ACTIVE,
                payload=ProjectArchiveUpdate(archived=True, expected_status="archived"),
                owner_actor_id=ACTOR_OWNER,
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 409

    # status は変わっていない + audit なし
    async with session_factory() as session:
        status = await session.scalar(
            text("select status from projects where id = :p"), {"p": PROJECT_ACTIVE}
        )
        assert status == "active"
        assert await _audit_events(session, TENANT_1) == []


@pytestmark_db
@pytest.mark.asyncio
async def test_archive_noop_same_status_writes_no_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """active のまま archived=False (no-op) は実遷移でないので audit を残さない (audit は実遷移と 1:1)。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        item = await update_project_archive_endpoint(
            project_id=PROJECT_ACTIVE,
            payload=ProjectArchiveUpdate(archived=False, expected_status="active"),
            owner_actor_id=ACTOR_OWNER,
            tenant_id=TENANT_1,
            session=session,
        )
        assert item.status == "active"

    async with session_factory() as session:
        assert await _audit_events(session, TENANT_1) == []


@pytestmark_db
@pytest.mark.asyncio
async def test_archive_unknown_project_returns_404(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await update_project_archive_endpoint(
                project_id=uuid4(),
                payload=ProjectArchiveUpdate(archived=True, expected_status="active"),
                owner_actor_id=ACTOR_OWNER,
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 404


@pytestmark_db
@pytest.mark.asyncio
async def test_archive_service_cas_raises_on_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """CAS は endpoint だけでなく service 境界 (ProjectArchiveService) で enforce する。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        service = ProjectArchiveService(session)
        with pytest.raises(ArchiveExpectationMismatch):
            await service.set_archived(
                tenant_id=TENANT_1,
                project_id=PROJECT_ACTIVE,
                archived=True,
                expected_status="archived",  # 実際は active
            )


# --------- owner gate (require_project_owner) ---------


@pytestmark_db
@pytest.mark.asyncio
async def test_require_project_owner_allows_authenticated_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        resolved = await require_project_owner(
            _fake_request(authenticated=True),  # type: ignore[arg-type]
            actor_id=ACTOR_OWNER,
            tenant_id=TENANT_1,
            session=session,
        )
        assert resolved == ACTOR_OWNER


@pytestmark_db
@pytest.mark.asyncio
async def test_require_project_owner_rejects_unauthenticated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await require_project_owner(
                _fake_request(authenticated=False),  # type: ignore[arg-type]
                actor_id=ACTOR_OWNER,  # owner として resolve されても
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 401


@pytestmark_db
@pytest.mark.asyncio
async def test_require_project_owner_rejects_non_owner_actors(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """別 human / service / agent / provider / github_app は 403 で fail-closed。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    for non_owner in (
        ACTOR_EXTRA_HUMAN,
        ACTOR_SERVICE,
        ACTOR_AGENT,
        ACTOR_PROVIDER,
        ACTOR_GITHUB_APP,
    ):
        async with session_factory() as session:
            with pytest.raises(HTTPException) as exc:
                await require_project_owner(
                    _fake_request(authenticated=True),  # type: ignore[arg-type]
                    actor_id=non_owner,
                    tenant_id=TENANT_1,
                    session=session,
                )
            assert exc.value.status_code == 403


# --------- archived child-write 凍結 (全 mutation 境界 = HTTP / MCP / research) ---------


@pytestmark_db
@pytest.mark.asyncio
async def test_create_in_project_on_archived_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """create_in_project (tickets.py HTTP + research-to-ticket promotion の共有経路) は
    archived project で ProjectArchivedError。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        with pytest.raises(ProjectArchivedError):
            await repo.create_in_project(
                TENANT_1,
                PROJECT_ARCHIVED,
                {"slug": "new-1", "title": "t", "created_by_actor_id": ACTOR_OWNER},
            )


@pytestmark_db
@pytest.mark.asyncio
async def test_update_in_project_on_archived_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """update_in_project (MCP bridge bridge_ticket_update の経路) は archived で凍結。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        # archived project に既存 ticket を直接 INSERT (guard を通さず seed)
        await session.execute(
            text(
                """
                insert into tickets (id, tenant_id, project_id, slug, title, status,
                  created_by_actor_id, metadata)
                values (:id, 1, :p, 'arch-t1', 'Arch', 'open', :a, '{"rls_ready": true}'::jsonb)
                """
            ),
            {"id": uuid4(), "p": PROJECT_ARCHIVED, "a": ACTOR_OWNER},
        )
        await session.commit()

    async with session_factory() as session:
        repo = TicketRepository(session)
        ticket_id = await session.scalar(
            text("select id from tickets where project_id = :p"), {"p": PROJECT_ARCHIVED}
        )
        with pytest.raises(ProjectArchivedError):
            await repo.update_in_project(
                TENANT_1, PROJECT_ARCHIVED, ticket_id, {"title": "changed"}
            )


@pytestmark_db
@pytest.mark.asyncio
async def test_mcp_bridge_ticket_create_on_archived_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (ADR-00037 R5 #2): MCP bridge bridge_ticket_create は archived project で
    ProjectArchivedError を出す。

    foundation では bridge_ticket_create が guard 無しの base ``create`` を踏んでいたため archived
    project へ書けていた。create_in_project へ修正 + base create 禁止で全 mutation 境界を凍結。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        with pytest.raises(ProjectArchivedError):
            await bridge_ticket_create(
                session,
                tenant_id=TENANT_1,
                project_id=PROJECT_ARCHIVED,
                title="via mcp",
            )

    # active project では作成できる (guard が active を妨げない回帰確認)
    async with session_factory() as session:
        result = await bridge_ticket_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            title="via mcp ok",
        )
        assert result["status"] == "open"


@pytestmark_db
@pytest.mark.asyncio
async def test_bulk_soft_delete_and_restore_on_archived_raise(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """archived project への bulk-soft-delete / restore は ProjectArchivedError (R5 #2)。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        repo = TicketRepository(session)
        with pytest.raises(ProjectArchivedError):
            # archived は CAS 前に raise するため expected 値は不問 (0 を渡す)。
            await repo.bulk_soft_delete_in_project(
                TENANT_1,
                PROJECT_ARCHIVED,
                expected_active_count=0,
                deleted_by_actor_id=ACTOR_OWNER,
            )
        with pytest.raises(ProjectArchivedError):
            await repo.restore_batch_in_project(TENANT_1, PROJECT_ARCHIVED, uuid4())


@pytestmark_db
@pytest.mark.asyncio
async def test_import_on_archived_returns_409(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await import_tickets_endpoint(
                project_id=PROJECT_ARCHIVED,
                payload=ImportTicketsRequest(tickets=[TicketImportItem(slug="i-1", title="t")]),
                owner_actor_id=ACTOR_OWNER,
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 409


# --------- Q-3 bulk-soft-delete + restore ---------


@pytestmark_db
@pytest.mark.asyncio
async def test_bulk_soft_delete_excludes_from_all_read_paths(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """soft-delete 後、list / get / count の全 default read path から除外される (active scope)。
    include_deleted=True でのみ可視。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["a-1", "a-2", "a-3"]
        )

    # bulk soft delete (endpoint, CAS expected=3)
    async with session_factory() as session:
        resp = await bulk_soft_delete_tickets_endpoint(
            project_id=PROJECT_ACTIVE,
            payload=BulkSoftDeleteRequest(expected_active_count=3),
            owner_actor_id=ACTOR_OWNER,
            tenant_id=TENANT_1,
            session=session,
        )
        assert resp.soft_deleted_count == 3

    # 全 read path から除外
    async with session_factory() as session:
        repo = TicketRepository(session)
        assert await repo.list_in_project(TENANT_1, PROJECT_ACTIVE) == []
        assert await repo.count_active_in_project(TENANT_1, PROJECT_ACTIVE) == 0
        # include_deleted では見える
        with_deleted = await repo.list_in_project(
            TENANT_1, PROJECT_ACTIVE, include_deleted=True
        )
        assert len(with_deleted) == 3
        # get も active scope (deleted は None)、include_deleted で取得可
        deleted_id = with_deleted[0].id
        assert (
            await repo.get_in_project(TENANT_1, PROJECT_ACTIVE, deleted_id) is None
        )
        assert (
            await repo.get_in_project(
                TENANT_1, PROJECT_ACTIVE, deleted_id, include_deleted=True
            )
            is not None
        )

    # audit (tickets_bulk_soft_deleted、batch_id + count)
    async with session_factory() as session:
        events = await _audit_events(session, TENANT_1)
        bulk = [e for e in events if e.event_type == "tickets_bulk_soft_deleted"]
        assert len(bulk) == 1
        assert bulk[0].event_payload["soft_deleted_count"] == 3
        assert "deleted_batch_id" in bulk[0].event_payload


@pytestmark_db
@pytest.mark.asyncio
async def test_bulk_soft_delete_cas_mismatch_returns_409(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """expected_active_count が DB current と不一致なら 409 (concurrent 変更検出、削除しない)。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["a-1", "a-2"]
        )

    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await bulk_soft_delete_tickets_endpoint(
                project_id=PROJECT_ACTIVE,
                payload=BulkSoftDeleteRequest(expected_active_count=5),  # 実際は 2
                owner_actor_id=ACTOR_OWNER,
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 409

    # 削除されていない + audit なし
    async with session_factory() as session:
        repo = TicketRepository(session)
        assert await repo.count_active_in_project(TENANT_1, PROJECT_ACTIVE) == 2
        assert await _audit_events(session, TENANT_1) == []


@pytestmark_db
@pytest.mark.asyncio
async def test_bulk_soft_delete_nonexistent_project_returns_404(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """存在しない project への bulk-delete は 404 (Codex adversarial #3、phantom batch/audit 防止)。

    存在しない project は active 件数 0 で、expected_active_count=0 と一致してしまうが、project
    不在を lock 取得時に検出し ProjectNotFoundError -> 404。audit を残さない。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await bulk_soft_delete_tickets_endpoint(
                project_id=uuid4(),
                payload=BulkSoftDeleteRequest(expected_active_count=0),
                owner_actor_id=ACTOR_OWNER,
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 404

    async with session_factory() as session:
        assert await _audit_events(session, TENANT_1) == []


@pytestmark_db
@pytest.mark.asyncio
async def test_bulk_soft_delete_empty_active_is_noop_without_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """active 0 件の project への bulk-delete (expected=0) は no-op: batch=None / 0 件 / audit なし
    (Codex adversarial #3、実遷移と 1:1)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        # PROJECT_ACTIVE は ticket を持たない (active 0 件)

    async with session_factory() as session:
        resp = await bulk_soft_delete_tickets_endpoint(
            project_id=PROJECT_ACTIVE,
            payload=BulkSoftDeleteRequest(expected_active_count=0),
            owner_actor_id=ACTOR_OWNER,
            tenant_id=TENANT_1,
            session=session,
        )
        assert resp.soft_deleted_count == 0
        assert resp.deleted_batch_id is None  # phantom batch を発行しない

    async with session_factory() as session:
        # no-op は audit を残さない
        events = [
            e
            for e in await _audit_events(session, TENANT_1)
            if e.event_type == "tickets_bulk_soft_deleted"
        ]
        assert events == []


@pytestmark_db
@pytest.mark.asyncio
async def test_bulk_soft_delete_cas_enforced_inside_repository(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """CAS は endpoint ではなく repository の atomic 操作内で enforce される (Codex adversarial #2)。

    repository を直接呼んで expected が現在と不一致なら BulkDeleteCountMismatch (project row lock
    保持下で count と判定)。これにより endpoint 外の caller も TOCTOU なしに CAS が効く。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["x-1", "x-2"]
        )

    async with session_factory() as session:
        repo = TicketRepository(session)
        with pytest.raises(BulkDeleteCountMismatch) as exc:
            await repo.bulk_soft_delete_in_project(
                TENANT_1,
                PROJECT_ACTIVE,
                expected_active_count=99,  # 実際は 2
                deleted_by_actor_id=ACTOR_OWNER,
            )
        assert exc.value.expected == 99
        assert exc.value.actual == 2

    # 何も削除されていない
    async with session_factory() as session:
        repo = TicketRepository(session)
        assert await repo.count_active_in_project(TENANT_1, PROJECT_ACTIVE) == 2


@pytestmark_db
@pytest.mark.asyncio
async def test_concurrent_archive_and_bulk_delete_are_serialized(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """archive と bulk-delete を並行実行しても project row lock で直列化され結果が一貫する
    (Codex adversarial #1/#2)。

    - deadlock しない (両 task が完了)。
    - bulk-delete は成功なら expected ちょうど 2 件削除 (未確認の余剰削除なし)、archived 後なら
      ProjectArchivedError で 0 件 block。
    - 最終的に「archived かつ active 2 件 (delete blocked)」か「archived かつ active 0 件
      (delete 先行)」のどちらか一貫した状態。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["c-1", "c-2"]
        )

    async def archive_task() -> tuple[str, bool]:
        async with session_factory() as session:
            service = ProjectArchiveService(session)
            result = await service.set_archived(
                tenant_id=TENANT_1,
                project_id=PROJECT_ACTIVE,
                archived=True,
                expected_status="active",
            )
            await session.commit()
            return ("archive", result is not None)

    async def bulk_delete_task() -> tuple[str, int]:
        async with session_factory() as session:
            repo = TicketRepository(session)
            try:
                _, count = await repo.bulk_soft_delete_in_project(
                    TENANT_1,
                    PROJECT_ACTIVE,
                    expected_active_count=2,
                    deleted_by_actor_id=ACTOR_OWNER,
                )
                await session.commit()
                return ("deleted", count)
            except (ProjectArchivedError, BulkDeleteCountMismatch):
                await session.rollback()
                return ("blocked", 0)

    results = await asyncio.gather(
        archive_task(), bulk_delete_task(), return_exceptions=True
    )
    for r in results:
        assert not isinstance(r, BaseException), f"unexpected exception (deadlock?): {r!r}"

    delete_outcome = next(r for r in results if r[0] in ("deleted", "blocked"))  # type: ignore[index]
    if delete_outcome[0] == "deleted":
        assert delete_outcome[1] == 2  # CAS 維持: 未確認の余剰削除なし

    # 最終状態の一貫性: project は archived、active 件数は delete の成否に対応 (0 or 2)。
    async with session_factory() as session:
        repo = TicketRepository(session)
        status = await session.scalar(
            text("select status from projects where id = :p"), {"p": PROJECT_ACTIVE}
        )
        active = await repo.count_active_in_project(TENANT_1, PROJECT_ACTIVE)
    assert status == "archived"
    assert active == (0 if delete_outcome[0] == "deleted" else 2)


@pytestmark_db
@pytest.mark.asyncio
async def test_restore_only_target_batch_and_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """2 つの batch を作り、片方だけ restore → 当該 batch のみ復活 (他 batch 不変)。
    再 restore は restored_count=0 (idempotent)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["a-1", "a-2"]
        )

    # batch 1: a-1, a-2 を soft delete
    async with session_factory() as session:
        repo = TicketRepository(session)
        batch1, count1 = await repo.bulk_soft_delete_in_project(
            TENANT_1,
            PROJECT_ACTIVE,
            expected_active_count=2,
            deleted_by_actor_id=ACTOR_OWNER,
        )
        await session.commit()
        assert count1 == 2

    # batch 2: 新 ticket a-3 を作り soft delete
    async with session_factory() as session:
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["a-3"]
        )
    async with session_factory() as session:
        repo = TicketRepository(session)
        batch2, count2 = await repo.bulk_soft_delete_in_project(
            TENANT_1,
            PROJECT_ACTIVE,
            expected_active_count=1,
            deleted_by_actor_id=ACTOR_OWNER,
        )
        await session.commit()
        assert count2 == 1

    # batch1 のみ restore
    async with session_factory() as session:
        restored = await restore_tickets_batch_endpoint(
            project_id=PROJECT_ACTIVE,
            payload=RestoreBatchRequest(deleted_batch_id=batch1),
            owner_actor_id=ACTOR_OWNER,
            tenant_id=TENANT_1,
            session=session,
        )
        assert restored.restored_count == 2

    async with session_factory() as session:
        repo = TicketRepository(session)
        active = {t.slug for t in await repo.list_in_project(TENANT_1, PROJECT_ACTIVE)}
        assert active == {"a-1", "a-2"}  # batch1 復活、batch2 (a-3) は deleted のまま
        all_deleted = [
            t
            for t in await repo.list_in_project(TENANT_1, PROJECT_ACTIVE, include_deleted=True)
            if t.deleted_at is not None
        ]
        assert {t.slug for t in all_deleted} == {"a-3"}

    # 再 restore (batch1) → idempotent 0 + audit なし
    async with session_factory() as session:
        again = await restore_tickets_batch_endpoint(
            project_id=PROJECT_ACTIVE,
            payload=RestoreBatchRequest(deleted_batch_id=batch1),
            owner_actor_id=ACTOR_OWNER,
            tenant_id=TENANT_1,
            session=session,
        )
        assert again.restored_count == 0

    async with session_factory() as session:
        events = await _audit_events(session, TENANT_1)
        restored_events = [e for e in events if e.event_type == "tickets_restored"]
        assert len(restored_events) == 1  # 0 件 restore は audit を残さない
        assert restored_events[0].event_payload["restored_count"] == 2


@pytestmark_db
@pytest.mark.asyncio
async def test_restore_cross_project_batch_id_resurrects_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """project A で発行した batch_id を project OTHER 経由で restore → 0 rows (越境復活なし)。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["a-1"]
        )

    async with session_factory() as session:
        repo = TicketRepository(session)
        batch, _ = await repo.bulk_soft_delete_in_project(
            TENANT_1,
            PROJECT_ACTIVE,
            expected_active_count=1,
            deleted_by_actor_id=ACTOR_OWNER,
        )
        await session.commit()

    # 別 project (OTHER) 経由で同 batch_id を restore → 越境せず 0
    async with session_factory() as session:
        resp = await restore_tickets_batch_endpoint(
            project_id=PROJECT_OTHER,
            payload=RestoreBatchRequest(deleted_batch_id=batch),
            owner_actor_id=ACTOR_OWNER,
            tenant_id=TENANT_1,
            session=session,
        )
        assert resp.restored_count == 0

    # project A の ticket は依然 deleted のまま (復活していない)
    async with session_factory() as session:
        repo = TicketRepository(session)
        assert await repo.count_active_in_project(TENANT_1, PROJECT_ACTIVE) == 0


@pytestmark_db
@pytest.mark.asyncio
async def test_bulk_soft_delete_is_tenant_and_project_scoped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """project A の bulk delete は同一 tenant の別 project (OTHER) と別 tenant を巻き込まない。

    tenant context は session 単位で 1 つに固定されるため、tenant ごとに session を分ける
    (既存 R-3 secret-refs test と同じ cross-tenant pattern)。
    """
    # tenant 1: ACTIVE (1) + OTHER (2) を seed
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["a-1"]
        )
    async with session_factory() as session:
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_OTHER, slugs=["o-1", "o-2"]
        )
    # tenant 2: T2 (1) を seed (別 session)
    async with session_factory() as session:
        await _seed_tickets(
            session, tenant_id=TENANT_2, project_id=PROJECT_T2, slugs=["t-1"]
        )

    async with session_factory() as session:
        repo = TicketRepository(session)
        _, count = await repo.bulk_soft_delete_in_project(
            TENANT_1,
            PROJECT_ACTIVE,
            expected_active_count=1,
            deleted_by_actor_id=ACTOR_OWNER,
        )
        await session.commit()
        assert count == 1  # PROJECT_ACTIVE の 1 件のみ

    # 同一 tenant の別 project は不変
    async with session_factory() as session:
        repo = TicketRepository(session)
        assert await repo.count_active_in_project(TENANT_1, PROJECT_OTHER) == 2
    # 別 tenant も不変 (別 session で tenant context を切替)
    async with session_factory() as session:
        repo = TicketRepository(session)
        assert await repo.count_active_in_project(TENANT_2, PROJECT_T2) == 1


@pytestmark_db
@pytest.mark.asyncio
async def test_mcp_cross_project_reads_exclude_soft_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R2 #2): MCP cross-project list_all / search が
    soft-deleted ticket を漏らさない (active scope 全 read path)。restore で再び可視になる。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["mcp-leak-1"]
        )

    # 削除前は MCP cross-project read に見える
    async with session_factory() as session:
        before = await bridge_ticket_search(session, tenant_id=TENANT_1, query="mcp-leak")
        assert len(before["tickets"]) == 1

    # soft delete
    async with session_factory() as session:
        repo = TicketRepository(session)
        batch, _ = await repo.bulk_soft_delete_in_project(
            TENANT_1,
            PROJECT_ACTIVE,
            expected_active_count=1,
            deleted_by_actor_id=ACTOR_OWNER,
        )
        await session.commit()

    # MCP cross-project list_all / search は削除済を返さない
    async with session_factory() as session:
        list_all = await bridge_ticket_list_all(session, tenant_id=TENANT_1, status="open")
        assert all("mcp-leak" not in t["title"] for t in list_all["tickets"])
        search = await bridge_ticket_search(session, tenant_id=TENANT_1, query="mcp-leak")
        assert search["tickets"] == []

    # restore で再び MCP read に可視
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.restore_batch_in_project(TENANT_1, PROJECT_ACTIVE, batch)
        await session.commit()
    async with session_factory() as session:
        search = await bridge_ticket_search(session, tenant_id=TENANT_1, query="mcp-leak")
        assert len(search["tickets"]) == 1


async def _first_ticket_id(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
) -> str:
    async with session_factory() as session:
        repo = TicketRepository(session)
        tickets = await repo.list_in_project(TENANT_1, project_id, include_deleted=True)
        return str(tickets[0].id)


@pytestmark_db
@pytest.mark.asyncio
async def test_assert_ticket_actionable_guard(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """work-initiation guard helper (Codex adversarial R3): active OK / soft-deleted・archived・
    不正 id は raise。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["act-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)

    # active ticket + active project: 通る
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.assert_ticket_actionable(TENANT_1, PROJECT_ACTIVE, ticket_id)

    # 形式不正 / 存在しない ticket_id: TicketNotActionableError
    async with session_factory() as session:
        repo = TicketRepository(session)
        with pytest.raises(TicketNotActionableError):
            await repo.assert_ticket_actionable(TENANT_1, PROJECT_ACTIVE, "not-a-uuid")
        with pytest.raises(TicketNotActionableError):
            await repo.assert_ticket_actionable(TENANT_1, PROJECT_ACTIVE, str(uuid4()))

    # soft-deleted ticket: TicketNotActionableError
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()
    async with session_factory() as session:
        repo = TicketRepository(session)
        with pytest.raises(TicketNotActionableError):
            await repo.assert_ticket_actionable(TENANT_1, PROJECT_ACTIVE, ticket_id)

    # archived project: ProjectArchivedError。archive は ticket を消さないので ticket は active の
    # まま残る。archived project には create できないため active project に作ってから archive する。
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["arch-act-1"]
        )
    arch_ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    async with session_factory() as session:
        service = ProjectArchiveService(session)
        await service.set_archived(
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            archived=True,
            expected_status="active",
        )
        await session.commit()
    async with session_factory() as session:
        repo = TicketRepository(session)
        with pytest.raises(ProjectArchivedError):
            await repo.assert_ticket_actionable(TENANT_1, PROJECT_ACTIVE, arch_ticket_id)


@pytestmark_db
@pytest.mark.asyncio
async def test_mcp_work_initiation_blocks_soft_deleted_and_archived(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R3): MCP work-initiation (run_create の chokepoint +
    approval_request_create) は soft-deleted ticket / archived project への作業開始を拒否する。
    削除/凍結した作業が AI 実行・承認・委譲・dispatch・コスト発生へ進むのを防ぐ。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["wi-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)

    # soft-delete 後: run_create / approval_request_create は guard で reject (作成前に raise)
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(TicketNotActionableError):
            await bridge_run_create(
                session,
                tenant_id=TENANT_1,
                project_id=PROJECT_ACTIVE,
                ticket_id=ticket_id,
                purpose="work on deleted ticket",
            )
    async with session_factory() as session:
        with pytest.raises(TicketNotActionableError):
            await bridge_approval_request_create(
                session,
                tenant_id=TENANT_1,
                project_id=PROJECT_ACTIVE,
                ticket_id=ticket_id,
                action_class="task_write",
                requester_actor_id=ACTOR_OWNER,
            )

    # archived project: active ticket を持つ project (OTHER) を archive してから run_create →
    # ProjectArchivedError (archive freeze は新規作業開始も凍結する)。
    async with session_factory() as session:
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_OTHER, slugs=["wi-arch-1"]
        )
    arch_ticket_id = await _first_ticket_id(session_factory, PROJECT_OTHER)
    async with session_factory() as session:
        service = ProjectArchiveService(session)
        await service.set_archived(
            tenant_id=TENANT_1,
            project_id=PROJECT_OTHER,
            archived=True,
            expected_status="active",
        )
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(ProjectArchivedError):
            await bridge_run_create(
                session,
                tenant_id=TENANT_1,
                project_id=PROJECT_OTHER,
                ticket_id=arch_ticket_id,
                purpose="work on archived project",
            )


@pytestmark_db
@pytest.mark.asyncio
async def test_mcp_ticket_comment_blocks_soft_deleted_and_archived(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R4 #2): bridge_ticket_comment は soft-deleted ticket /
    archived project への comment (作業ログ event) を拒否する (notification_events は ticket FK を
    持たないため guard で塞ぐ)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["cm-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)

    # active ticket では comment 作成可能
    async with session_factory() as session:
        result = await bridge_ticket_comment(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            ticket_id=UUID(ticket_id),
            message="active comment",
            actor_id=ACTOR_OWNER,
        )
        assert "comment_id" in result

    # soft-delete 後は TicketNotActionableError
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(TicketNotActionableError):
            await bridge_ticket_comment(
                session,
                tenant_id=TENANT_1,
                project_id=PROJECT_ACTIVE,
                ticket_id=UUID(ticket_id),
                message="comment on deleted",
                actor_id=ACTOR_OWNER,
            )

    # archived project は ProjectArchivedError
    async with session_factory() as session:
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_OTHER, slugs=["cm-arch-1"]
        )
    arch_ticket_id = await _first_ticket_id(session_factory, PROJECT_OTHER)
    async with session_factory() as session:
        service = ProjectArchiveService(session)
        await service.set_archived(
            tenant_id=TENANT_1,
            project_id=PROJECT_OTHER,
            archived=True,
            expected_status="active",
        )
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(ProjectArchivedError):
            await bridge_ticket_comment(
                session,
                tenant_id=TENANT_1,
                project_id=PROJECT_OTHER,
                ticket_id=UUID(arch_ticket_id),
                message="comment on archived",
                actor_id=ACTOR_OWNER,
            )


@pytestmark_db
@pytest.mark.asyncio
async def test_superintendent_dispatch_approval_path_blocks_deleted_ticket(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R4 #1): superintendent_dispatch の承認待ち経路が
    bridge_run_create の guard 例外を成功応答に変換しない。削除済 ticket への task_write dispatch は
    error dict (dispatched=False) を返し、承認通知も出さない。

    MCP tool は get_db_session() (= test の TASKMANAGEDAI_DATABASE_URL) を使うため、session_factory で
    seed + soft-delete した ticket を dispatch から参照できる。
    """
    from backend.app.mcp.server import superintendent_dispatch

    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["disp-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()

    # conservative policy + task_write は承認待ち経路。削除済 ticket で guard が効き error を返す。
    result = await superintendent_dispatch(
        agent_id="00000000-0000-4000-8000-000000000099",
        ticket_id=ticket_id,
        action_class="task_write",
        project_id=str(PROJECT_ACTIVE),
    )
    assert result.get("dispatched") is not True  # 成功に変換しない
    assert result.get("error") == "TicketNotActionableError"


@pytestmark_db
@pytest.mark.asyncio
async def test_ticket_relation_blocks_soft_deleted_and_archived(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R5 #2): ticket relation 作成は active ticket 同士 / active
    project のみ許可し、soft-deleted ticket / archived project を拒否する。bridge_ticket_link の
    signature 修正 (payload= → source_id/target_id) も active 経路で確認する。
    """
    from backend.app.mcp.api_bridge import bridge_ticket_link
    from backend.app.repositories.ticket_relation import TicketRelationRepository

    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["rel-a", "rel-b"]
        )
    async with session_factory() as session:
        repo = TicketRepository(session)
        ids = [t.id for t in await repo.list_in_project(TENANT_1, PROJECT_ACTIVE)]
    src, tgt = ids[0], ids[1]

    # active: bridge_ticket_link (signature 修正後) が成功する
    async with session_factory() as session:
        result = await bridge_ticket_link(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            source_ticket_id=src,
            target_ticket_id=tgt,
            relation_type="depends_on",
        )
        assert "relation_id" in result

    # soft-delete 後: 両 ticket が deleted → 新 relation は active ticket でないため ValueError
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=2, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()
    async with session_factory() as session:
        rel_repo = TicketRelationRepository(session)
        with pytest.raises(ValueError):
            await rel_repo.create_in_project(
                TENANT_1, PROJECT_ACTIVE, source_id=src, target_id=tgt, relation_type="blocks"
            )

    # archived project: active ticket 2 件を作って archive → relation 作成は ProjectArchivedError
    async with session_factory() as session:
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_OTHER, slugs=["rel-c", "rel-d"]
        )
    async with session_factory() as session:
        repo = TicketRepository(session)
        other_ids = [t.id for t in await repo.list_in_project(TENANT_1, PROJECT_OTHER)]
    async with session_factory() as session:
        service = ProjectArchiveService(session)
        await service.set_archived(
            tenant_id=TENANT_1,
            project_id=PROJECT_OTHER,
            archived=True,
            expected_status="active",
        )
        await session.commit()
    async with session_factory() as session:
        rel_repo = TicketRelationRepository(session)
        with pytest.raises(ProjectArchivedError):
            await rel_repo.create_in_project(
                TENANT_1,
                PROJECT_OTHER,
                source_id=other_ids[0],
                target_id=other_ids[1],
                relation_type="depends_on",
            )


@pytestmark_db
@pytest.mark.asyncio
async def test_http_ticket_create_update_on_archived_return_409(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R5 #3): HTTP tickets create/update が archived project で
    ProjectArchivedError を 409 に写像する (未捕捉だと 500)。
    """
    from backend.app.api.tickets import (
        TicketCreateRequest,
        TicketUpdateRequest,
        create_ticket_endpoint,
        update_ticket_endpoint,
    )

    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["http-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    async with session_factory() as session:
        service = ProjectArchiveService(session)
        await service.set_archived(
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            archived=True,
            expected_status="active",
        )
        await session.commit()

    # create on archived → 409
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await create_ticket_endpoint(
                project_id=PROJECT_ACTIVE,
                payload=TicketCreateRequest(slug="new-on-arch", title="X"),
                actor_id=ACTOR_OWNER,
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 409

    # update on archived → 409
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await update_ticket_endpoint(
                project_id=PROJECT_ACTIVE,
                ticket_id=UUID(ticket_id),
                payload=TicketUpdateRequest(title="changed"),
                actor_id=ACTOR_OWNER,
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 409


@pytestmark_db
@pytest.mark.asyncio
async def test_existing_run_cannot_advance_after_ticket_deleted_or_archived(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R6): bulk soft-delete / archive **前**に作成済みの既存 run は、
    ticket 削除 / project archive 後に bridge_run_update で advance できない (削除/凍結した作業が
    AI 実行・コスト・結果公開へ進むのを防ぐ)。binding 先 ticket を run_queued event から解決して guard。
    """
    # --- soft-delete case (PROJECT_ACTIVE) ---
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["run-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    async with session_factory() as session:
        created = await bridge_run_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            ticket_id=ticket_id,
            purpose="work",
        )
        run_id = UUID(created["run_id"])
    # ticket を soft-delete してから既存 run を advance しようとする
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()
    async with session_factory() as session:
        result = await bridge_run_update(
            session, tenant_id=TENANT_1, run_id=run_id, status="running"
        )
        assert result.get("error") == "TicketNotActionableError"

    # --- archived case (PROJECT_OTHER) ---
    async with session_factory() as session:
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_OTHER, slugs=["run-2"]
        )
    other_ticket_id = await _first_ticket_id(session_factory, PROJECT_OTHER)
    async with session_factory() as session:
        created2 = await bridge_run_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_OTHER,
            ticket_id=other_ticket_id,
            purpose="work2",
        )
        run_id2 = UUID(created2["run_id"])
    async with session_factory() as session:
        service = ProjectArchiveService(session)
        await service.set_archived(
            tenant_id=TENANT_1,
            project_id=PROJECT_OTHER,
            archived=True,
            expected_status="active",
        )
        await session.commit()
    async with session_factory() as session:
        result2 = await bridge_run_update(
            session, tenant_id=TENANT_1, run_id=run_id2, status="running"
        )
        assert result2.get("error") == "ProjectArchivedError"


@pytestmark_db
@pytest.mark.asyncio
async def test_run_advance_uses_server_owned_ticket_binding(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R7 #1 + R12): run-transition guard は server-owned column
    (run.ticket_id) を直読みする。run_queued event payload を破損しても、column binding で soft-deleted
    ticket を検出し advance を fail-closed で block する (event-payload 依存の fail-open / 非決定性なし)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["fc-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    async with session_factory() as session:
        created = await bridge_run_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            ticket_id=ticket_id,
            purpose="work",
        )
        run_id = created["run_id"]
    # run_queued event payload を破損させる。run.ticket_id column が binding source なので影響しない。
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE agent_run_events SET event_payload = '{}'::jsonb "
                "WHERE tenant_id = :tid AND run_id = :rid AND event_type = 'run_queued'"
            ),
            {"tid": TENANT_1, "rid": run_id},
        )
        await session.commit()
    # ticket を soft-delete
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()
    # event 破損でも column binding (run.ticket_id) で soft-deleted を検出 → fail-closed で block。
    async with session_factory() as session:
        result = await bridge_run_update(
            session, tenant_id=TENANT_1, run_id=UUID(run_id), status="running"
        )
        assert result.get("error") == "TicketNotActionableError"


@pytestmark_db
@pytest.mark.asyncio
async def test_import_on_archived_returns_409_before_slug_conflict_and_dry_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R7 #2): archived project への import は slug conflict / dry_run に
    関わらず archive guard が先に効き常に 409 (422 conflict / dry_run preview にならない)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["taken"]
        )
    async with session_factory() as session:
        service = ProjectArchiveService(session)
        await service.set_archived(
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            archived=True,
            expected_status="active",
        )
        await session.commit()

    # 既存 slug と衝突する import: archived なので 409 (422 conflict より archive guard が先)
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await import_tickets_endpoint(
                project_id=PROJECT_ACTIVE,
                payload=ImportTicketsRequest(
                    tickets=[TicketImportItem(slug="taken", title="x")]
                ),
                owner_actor_id=ACTOR_OWNER,
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 409

    # dry_run も archived では 409 (preview を返さない)
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await import_tickets_endpoint(
                project_id=PROJECT_ACTIVE,
                payload=ImportTicketsRequest(
                    tickets=[TicketImportItem(slug="fresh", title="y")], dry_run=True
                ),
                owner_actor_id=ACTOR_OWNER,
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 409


@pytestmark_db
@pytest.mark.asyncio
async def test_dogfooding_seed_existing_query_excludes_soft_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R9): dogfooding seed の既存 ticket 索引
    (_query_existing_dogfooding_tickets) は active scope (deleted_at IS NULL)。bulk soft-delete 済みの
    dogfooding ticket を「既存 active」扱いせず、re-run で hidden row を更新・保持しない。
    """
    from backend.app.cli.dogfooding_seed import _query_existing_dogfooding_tickets
    from backend.app.seeds.initial import (
        DEFAULT_ACTOR_ID,
        DEFAULT_PROJECT_ID,
        DEFAULT_WORKSPACE_ID,
    )

    async with session_factory() as session:
        await _reset_tables(session)
        await session.execute(
            text(
                "insert into tenants (id, name, metadata) "
                "values (1, 'default-tenant', '{\"rls_ready\": true}'::jsonb)"
            )
        )
        await session.execute(
            text(
                "insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata) "
                "values (:a, 1, 'human', 'human:default', 'Default', '{\"rls_ready\": true}'::jsonb)"
            ),
            {"a": DEFAULT_ACTOR_ID},
        )
        await session.execute(
            text(
                "insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata) "
                "values (:w, 1, 'default-workspace', 'default', :a, '{\"rls_ready\": true}'::jsonb)"
            ),
            {"w": DEFAULT_WORKSPACE_ID, "a": DEFAULT_ACTOR_ID},
        )
        await session.execute(
            text(
                "insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata) "
                "values (:p, 1, :w, 'default-project', 'default', 'active', "
                "'{\"rls_ready\": true}'::jsonb)"
            ),
            {"p": DEFAULT_PROJECT_ID, "w": DEFAULT_WORKSPACE_ID},
        )
        # active + soft-deleted の dogfooding ticket
        await session.execute(
            text(
                "insert into tickets (id, tenant_id, project_id, slug, title, status, "
                "created_by_actor_id, metadata) values (:t, 1, :p, 'dogfooding-sprint-active', 'A', "
                "'open', :a, '{\"rls_ready\": true}'::jsonb)"
            ),
            {"t": uuid4(), "p": DEFAULT_PROJECT_ID, "a": DEFAULT_ACTOR_ID},
        )
        await session.execute(
            text(
                "insert into tickets (id, tenant_id, project_id, slug, title, status, "
                "created_by_actor_id, deleted_at, metadata) values (:t, 1, :p, "
                "'dogfooding-sprint-deleted', 'D', 'open', :a, now(), '{\"rls_ready\": true}'::jsonb)"
            ),
            {"t": uuid4(), "p": DEFAULT_PROJECT_ID, "a": DEFAULT_ACTOR_ID},
        )
        await session.commit()

    async with session_factory() as session:
        existing = await _query_existing_dogfooding_tickets(session)
        slugs = set(existing.keys())
        assert "dogfooding-sprint-active" in slugs
        assert "dogfooding-sprint-deleted" not in slugs  # soft-deleted は除外


@pytestmark_db
@pytest.mark.asyncio
async def test_require_active_project_guard_blocks_archived_child_write(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R10 #1): 共通 guard require_active_project は archived project への
    child write (claim / evidence 等) を 409 で凍結し、active project は通す。
    """
    from backend.app.api.dependencies.project_active_guard import require_active_project

    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
    async with session_factory() as session:
        service = ProjectArchiveService(session)
        await service.set_archived(
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            archived=True,
            expected_status="active",
        )
        await session.commit()

    # archived project → 409
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await require_active_project(
                project_id=PROJECT_ACTIVE, tenant_id=TENANT_1, session=session
            )
        assert exc.value.status_code == 409
    # active project (OTHER) → 通る (例外なし)
    async with session_factory() as session:
        await require_active_project(
            project_id=PROJECT_OTHER, tenant_id=TENANT_1, session=session
        )


@pytestmark_db
@pytest.mark.asyncio
async def test_delegation_review_blocks_deleted_or_archived_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R10 #2): bridge_delegation_review は削除済 ticket / archived
    project の run に review (approval_decided) event を記録しない (R6 run guard を delegation_review にも適用)。
    """
    from backend.app.mcp.api_bridge import bridge_delegation_review

    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["rev-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    async with session_factory() as session:
        created = await bridge_run_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            ticket_id=ticket_id,
            purpose="work",
        )
        run_id = UUID(created["run_id"])
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()
    # 削除済 ticket の run への review は guard で block (reviewer 検証より前)
    async with session_factory() as session:
        result = await bridge_delegation_review(
            session,
            tenant_id=TENANT_1,
            run_id=run_id,
            reviewer_run_id=uuid4(),
            decision="adopt",
            quality_score=0.9,
        )
        assert result.get("error") == "TicketNotActionableError"


@pytestmark_db
@pytest.mark.asyncio
async def test_run_cost_blocks_deleted_run_and_leaves_cost_unchanged(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R11): bridge_run_cost は削除済 ticket / archived project の run の
    cost/token を更新しない (R6/R10 run-transition guard 対象に run_cost を追加、削除/凍結した作業の
    cost 計上・KPI 汚染を防ぐ)。error を返し cost columns は不変。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["cost-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    async with session_factory() as session:
        created = await bridge_run_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            ticket_id=ticket_id,
            purpose="work",
        )
        run_id = UUID(created["run_id"])
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()
    # 削除済 ticket の run の cost 更新は guard で block
    async with session_factory() as session:
        result = await bridge_run_cost(
            session,
            tenant_id=TENANT_1,
            run_id=run_id,
            cost_usd=9.99,
            tokens_input=1000,
            tokens_output=500,
        )
        assert result.get("error") == "TicketNotActionableError"
    # cost columns は更新されていない (初期 None / 0 のまま)
    async with session_factory() as session:
        row = await session.execute(
            text("select cost_usd, tokens_input, tokens_output from agent_runs where id = :r"),
            {"r": run_id},
        )
        cost_usd, tok_in, tok_out = row.one()
        assert (cost_usd, tok_in, tok_out) != (9.99, 1000, 500)


@pytestmark_db
@pytest.mark.asyncio
async def test_cost_summary_excludes_soft_deleted_ticket_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R12): cost/KPI 集計は soft-deleted ticket bound の run を除外する
    (KPI も active-scope read path)。active 時に計上した cost が ticket 削除後に集計から消え、restore で
    再び含まれる。run.ticket_id (server-owned binding) を tickets に JOIN し deleted_at で除外。
    """
    from backend.app.api.agent_runs import cost_summary_endpoint

    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["cost-kpi-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    async with session_factory() as session:
        created = await bridge_run_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            ticket_id=ticket_id,
            purpose="work",
        )
        run_id = UUID(created["run_id"])
    # ticket active 時に cost を計上
    async with session_factory() as session:
        await bridge_run_cost(
            session,
            tenant_id=TENANT_1,
            run_id=run_id,
            cost_usd=5.0,
            tokens_input=100,
            tokens_output=50,
        )

    # 削除前: cost summary に計上される
    async with session_factory() as session:
        resp = await cost_summary_endpoint(
            range_value="all", actor_id=ACTOR_OWNER, tenant_id=TENANT_1, session=session
        )
        assert resp.total_cost_usd == 5.0

    # soft-delete
    async with session_factory() as session:
        repo = TicketRepository(session)
        batch, _ = await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()

    # 削除後: cost summary から除外 (measured 0 → total_cost_usd None)
    async with session_factory() as session:
        resp = await cost_summary_endpoint(
            range_value="all", actor_id=ACTOR_OWNER, tenant_id=TENANT_1, session=session
        )
        assert resp.total_cost_usd is None

    # restore: 再び集計対象になる
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.restore_batch_in_project(TENANT_1, PROJECT_ACTIVE, batch)
        await session.commit()
    async with session_factory() as session:
        resp = await cost_summary_endpoint(
            range_value="all", actor_id=ACTOR_OWNER, tenant_id=TENANT_1, session=session
        )
        assert resp.total_cost_usd == 5.0


# --------- Q-2 import ---------


@pytestmark_db
@pytest.mark.asyncio
async def test_import_valid_inserts_all_and_audits(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        resp = await import_tickets_endpoint(
            project_id=PROJECT_ACTIVE,
            payload=ImportTicketsRequest(
                tickets=[
                    TicketImportItem(slug="imp-1", title="One"),
                    TicketImportItem(slug="imp-2", title="Two", status="in_progress"),
                ]
            ),
            owner_actor_id=ACTOR_OWNER,
            tenant_id=TENANT_1,
            session=session,
        )
        assert resp.valid is True
        assert resp.imported_count == 2
        assert resp.dry_run is False

    async with session_factory() as session:
        repo = TicketRepository(session)
        tickets = await repo.list_in_project(TENANT_1, PROJECT_ACTIVE)
        by_slug = {t.slug: t for t in tickets}
        assert set(by_slug) == {"imp-1", "imp-2"}
        assert by_slug["imp-2"].status == "in_progress"
        # server-owned 注入確認
        assert by_slug["imp-1"].created_by_actor_id == ACTOR_OWNER
        events = await _audit_events(session, TENANT_1)
        imported = [e for e in events if e.event_type == "tickets_imported"]
        assert len(imported) == 1
        assert imported[0].event_payload["imported_count"] == 2


@pytestmark_db
@pytest.mark.asyncio
async def test_import_in_payload_duplicate_slug_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """in-payload で同 slug 重複 → 422 で全体 reject (partial write なし)。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await import_tickets_endpoint(
                project_id=PROJECT_ACTIVE,
                payload=ImportTicketsRequest(
                    tickets=[
                        TicketImportItem(slug="dup", title="A"),
                        TicketImportItem(slug="dup", title="B"),
                        TicketImportItem(slug="ok", title="C"),
                    ]
                ),
                owner_actor_id=ACTOR_OWNER,
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 422
        assert "dup" in exc.value.detail["in_payload_duplicate_slugs"]  # type: ignore[index]

    async with session_factory() as session:
        repo = TicketRepository(session)
        assert await repo.list_in_project(TENANT_1, PROJECT_ACTIVE) == []  # no partial write


@pytestmark_db
@pytest.mark.asyncio
async def test_import_existing_active_slug_conflict_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["existing"]
        )

    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await import_tickets_endpoint(
                project_id=PROJECT_ACTIVE,
                payload=ImportTicketsRequest(
                    tickets=[
                        TicketImportItem(slug="existing", title="dup"),
                        TicketImportItem(slug="new", title="new"),
                    ]
                ),
                owner_actor_id=ACTOR_OWNER,
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 422
        assert "existing" in exc.value.detail["existing_conflict_slugs"]  # type: ignore[index]

    async with session_factory() as session:
        repo = TicketRepository(session)
        slugs = {t.slug for t in await repo.list_in_project(TENANT_1, PROJECT_ACTIVE)}
        assert slugs == {"existing"}  # "new" は insert されていない


@pytestmark_db
@pytest.mark.asyncio
async def test_import_existing_deleted_slug_conflict_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """soft-deleted ticket の slug も予約 (全行 unique)。delete 済 slug の再利用は reject。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["reused"]
        )
    # soft delete
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1,
            PROJECT_ACTIVE,
            expected_active_count=1,
            deleted_by_actor_id=ACTOR_OWNER,
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await import_tickets_endpoint(
                project_id=PROJECT_ACTIVE,
                payload=ImportTicketsRequest(
                    tickets=[TicketImportItem(slug="reused", title="re")]
                ),
                owner_actor_id=ACTOR_OWNER,
                tenant_id=TENANT_1,
                session=session,
            )
        assert exc.value.status_code == 422
        assert "reused" in exc.value.detail["existing_conflict_slugs"]  # type: ignore[index]


@pytestmark_db
@pytest.mark.asyncio
async def test_import_dry_run_does_not_insert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """dry_run=True は validation 結果のみ返し insert しない (preview)。"""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    async with session_factory() as session:
        resp = await import_tickets_endpoint(
            project_id=PROJECT_ACTIVE,
            payload=ImportTicketsRequest(
                tickets=[TicketImportItem(slug="dr-1", title="t")], dry_run=True
            ),
            owner_actor_id=ACTOR_OWNER,
            tenant_id=TENANT_1,
            session=session,
        )
        assert resp.dry_run is True
        assert resp.valid is True
        assert resp.imported_count == 0

    async with session_factory() as session:
        repo = TicketRepository(session)
        assert await repo.list_in_project(TENANT_1, PROJECT_ACTIVE) == []
        assert await _audit_events(session, TENANT_1) == []


@pytestmark_db
@pytest.mark.asyncio
async def test_import_dry_run_reports_conflicts_without_insert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["taken"]
        )

    async with session_factory() as session:
        resp = await import_tickets_endpoint(
            project_id=PROJECT_ACTIVE,
            payload=ImportTicketsRequest(
                tickets=[
                    TicketImportItem(slug="taken", title="x"),
                    TicketImportItem(slug="d", title="a"),
                    TicketImportItem(slug="d", title="b"),
                ],
                dry_run=True,
            ),
            owner_actor_id=ACTOR_OWNER,
            tenant_id=TENANT_1,
            session=session,
        )
        assert resp.valid is False
        assert resp.imported_count == 0
        assert resp.existing_conflict_slugs == ["taken"]
        assert resp.in_payload_duplicate_slugs == ["d"]

    async with session_factory() as session:
        repo = TicketRepository(session)
        assert {t.slug for t in await repo.list_in_project(TENANT_1, PROJECT_ACTIVE)} == {"taken"}


@pytestmark_db
@pytest.mark.asyncio
async def test_import_repository_db_unique_violation_rolls_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """DB-level 最終防衛: pre-validation をすり抜けて重複 slug が insert されると
    UNIQUE 違反で IntegrityError、partial write は rollback で残らない (並行 import 模擬)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["pre-existing"]
        )

    # endpoint の pre-check を回避して repository を直接呼ぶ (並行 import 模擬: 既存 slug を含む)
    async with session_factory() as session:
        repo = TicketRepository(session)
        items: list[dict[str, Any]] = [
            {
                "slug": "fresh",
                "title": "Fresh",
                "status": "open",
                "created_by_actor_id": ACTOR_OWNER,
                "metadata_": {"rls_ready": True},
            },
            {
                "slug": "pre-existing",  # 既に存在 → UNIQUE 違反
                "title": "Dup",
                "status": "open",
                "created_by_actor_id": ACTOR_OWNER,
                "metadata_": {"rls_ready": True},
            },
        ]
        with pytest.raises(IntegrityError):
            await repo.import_tickets_in_project(TENANT_1, PROJECT_ACTIVE, items)
        await session.rollback()

    # rollback 後、partial write ("fresh") は残らない
    async with session_factory() as session:
        repo = TicketRepository(session)
        slugs = {t.slug for t in await repo.list_in_project(TENANT_1, PROJECT_ACTIVE)}
        assert slugs == {"pre-existing"}
        assert "fresh" not in slugs


# --------- R13 (Codex adversarial): server-owned ticket_id 境界 ---------


@pytestmark_db
@pytest.mark.asyncio
async def test_workflow_status_excludes_soft_deleted_ticket_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R13 #2): MCP workflow summary も active-scope read path。
    soft-deleted ticket bound の run を total_runs / active 集計から除外し、restore で再び含める
    (cost_summary_endpoint / kpi_show と同じ run.ticket_id JOIN + deleted_at 除外)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["wf-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    async with session_factory() as session:
        await bridge_run_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            ticket_id=ticket_id,
            purpose="work",
        )

    # 削除前: workflow summary に計上 (queued は active)
    async with session_factory() as session:
        before = await bridge_workflow_status(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE
        )
        assert before["total_runs"] == 1
        assert before["active"] == 1

    # soft-delete
    async with session_factory() as session:
        repo = TicketRepository(session)
        batch, _ = await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()

    # 削除後: workflow summary から除外 (project 指定 / 全体 tenant の両 query path)
    async with session_factory() as session:
        after = await bridge_workflow_status(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE
        )
        assert after["total_runs"] == 0
        assert after["active"] == 0
    async with session_factory() as session:
        after_all = await bridge_workflow_status(session, tenant_id=TENANT_1)
        assert after_all["total_runs"] == 0

    # restore: 再び集計対象になる
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.restore_batch_in_project(TENANT_1, PROJECT_ACTIVE, batch)
        await session.commit()
    async with session_factory() as session:
        restored = await bridge_workflow_status(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE
        )
        assert restored["total_runs"] == 1


@pytestmark_db
@pytest.mark.asyncio
async def test_run_ticket_fk_enforces_same_project_binding(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R13 #1): server-owned agent_runs.ticket_id は複合 FK
    (tenant_id, project_id, ticket_id) -> tickets(tenant_id, project_id, id) で DB レベルに境界化。
    cross-project ticket binding は IntegrityError、同一 project は OK、ticket-less (NULL) は OK。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["same"]
        )
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_OTHER, slugs=["other"]
        )
    same_ticket = UUID(await _first_ticket_id(session_factory, PROJECT_ACTIVE))
    other_ticket = UUID(await _first_ticket_id(session_factory, PROJECT_OTHER))

    insert_run = text(
        "INSERT INTO agent_runs (id, tenant_id, project_id, ticket_id, status) "
        "VALUES (:id, :tid, :pid, :ticket, 'queued')"
    )

    # ticket-less run (NULL) は許可 (MATCH SIMPLE で FK 未強制)
    async with session_factory() as session:
        await session.execute(
            insert_run,
            {"id": uuid4(), "tid": TENANT_1, "pid": PROJECT_ACTIVE, "ticket": None},
        )
        await session.commit()

    # 同一 project の ticket binding は許可
    async with session_factory() as session:
        await session.execute(
            insert_run,
            {"id": uuid4(), "tid": TENANT_1, "pid": PROJECT_ACTIVE, "ticket": same_ticket},
        )
        await session.commit()

    # cross-project ticket binding は複合 FK が DB レベルで reject
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                insert_run,
                {"id": uuid4(), "tid": TENANT_1, "pid": PROJECT_ACTIVE, "ticket": other_ticket},
            )
            await session.commit()
        await session.rollback()


@pytestmark_db
@pytest.mark.asyncio
async def test_delegation_review_rejects_cross_project_reviewer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R14 #1, bounded): bridge_delegation_review の reviewer は
    同一 (tenant_id, project_id) の run のみ。cross-project reviewer (同一 tenant 別 project) は
    reviewer_not_found で reject し、project 越境レビューで approval_decided event を捏造させない
    (core.md §8 project 境界)。reviewer role/scope・delegation tree 帰属検証は defer (ADR 残リスク §)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["reviewed"]
        )
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_OTHER, slugs=["reviewer"]
        )
    reviewed_ticket = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    reviewer_ticket = await _first_ticket_id(session_factory, PROJECT_OTHER)

    async with session_factory() as session:
        reviewed = await bridge_run_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            ticket_id=reviewed_ticket,
            purpose="work",
        )
        reviewed_run_id = UUID(reviewed["run_id"])
    async with session_factory() as session:
        reviewer = await bridge_run_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_OTHER,
            ticket_id=reviewer_ticket,
            purpose="review",
        )
        cross_project_reviewer_id = UUID(reviewer["run_id"])

    # cross-project reviewer は project 境界で弾かれる (reviewer_not_found)
    async with session_factory() as session:
        result = await bridge_delegation_review(
            session,
            tenant_id=TENANT_1,
            run_id=reviewed_run_id,
            reviewer_run_id=cross_project_reviewer_id,
            decision="adopt",
            quality_score=0.9,
        )
        assert result.get("error") == "reviewer_not_found"

    # approval_decided event は記録されていない (越境レビューの監査捏造なし)
    async with session_factory() as session:
        decided = await session.execute(
            text(
                "SELECT count(*) FROM agent_run_events "
                "WHERE tenant_id = :tid AND run_id = :rid AND event_type = 'approval_decided'"
            ),
            {"tid": TENANT_1, "rid": reviewed_run_id},
        )
        assert decided.scalar_one() == 0


@pytestmark_db
@pytest.mark.asyncio
async def test_run_read_paths_exclude_soft_deleted_ticket_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R15 #2): soft-deleted ticket bound の run は **全 default read
    path** (HTTP list/detail/kpi + MCP run_list/run_show) から隠れる。restore で再び現れる。
    ticket-less run は対象外なので一覧に残る。共通 predicate soft_deleted_ticket_run_exclusion。
    """
    from backend.app.api.agent_runs import (
        get_agent_run_endpoint,
        list_agent_runs_endpoint,
    )

    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["read-path-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    async with session_factory() as session:
        created = await bridge_run_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            ticket_id=ticket_id,
            purpose="work",
        )
        run_id = UUID(created["run_id"])

    # 削除前: 全 read path で見える
    async with session_factory() as session:
        listed = await list_agent_runs_endpoint(
            status_filter=None, role=None, limit=50, offset=0,
            actor_id=ACTOR_OWNER, tenant_id=TENANT_1, session=session,
        )
        assert listed.total == 1
        detail = await get_agent_run_endpoint(
            run_id=run_id, actor_id=ACTOR_OWNER, tenant_id=TENANT_1, session=session
        )
        assert str(detail.id) == str(run_id)
        mcp_list = await bridge_run_list(session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE)
        assert mcp_list["total"] == 1
        mcp_show = await bridge_run_show(session, tenant_id=TENANT_1, run_id=run_id)
        assert mcp_show["run_id"] == str(run_id)
        assert mcp_show["ticket_id"] == ticket_id  # server-owned column 由来

    # soft-delete
    async with session_factory() as session:
        repo = TicketRepository(session)
        batch, _ = await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()

    # 削除後: list は 0、detail/kpi は 404、MCP list は 0、show は not_found
    async with session_factory() as session:
        listed = await list_agent_runs_endpoint(
            status_filter=None, role=None, limit=50, offset=0,
            actor_id=ACTOR_OWNER, tenant_id=TENANT_1, session=session,
        )
        assert listed.total == 0
        with pytest.raises(HTTPException) as exc:
            await get_agent_run_endpoint(
                run_id=run_id, actor_id=ACTOR_OWNER, tenant_id=TENANT_1, session=session
            )
        assert exc.value.status_code == 404
        mcp_list = await bridge_run_list(session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE)
        assert mcp_list["total"] == 0
        mcp_show = await bridge_run_show(session, tenant_id=TENANT_1, run_id=run_id)
        assert mcp_show.get("error") == "not_found"

    # restore: 再び全 read path で見える
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.restore_batch_in_project(TENANT_1, PROJECT_ACTIVE, batch)
        await session.commit()
    async with session_factory() as session:
        listed = await list_agent_runs_endpoint(
            status_filter=None, role=None, limit=50, offset=0,
            actor_id=ACTOR_OWNER, tenant_id=TENANT_1, session=session,
        )
        assert listed.total == 1
        mcp_show = await bridge_run_show(session, tenant_id=TENANT_1, run_id=run_id)
        assert mcp_show["run_id"] == str(run_id)


@pytestmark_db
@pytest.mark.asyncio
async def test_delegation_review_rejects_deleted_ticket_reviewer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R15 #3): reviewer run 自体が soft-deleted ticket に bind されて
    いれば bridge_delegation_review は reject する。active-scope 外の reviewer identity で
    approval_decided を捏造させない (R14 cross-project 境界とは別の soft-delete 境界の漏れ)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["reviewer-old"]
        )
    reviewer_ticket = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    # reviewer run を作成 (ticket active 時)
    async with session_factory() as session:
        reviewer = await bridge_run_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            ticket_id=reviewer_ticket,
            purpose="review",
        )
        reviewer_run_id = UUID(reviewer["run_id"])
    # bulk soft-delete で reviewer の ticket を削除
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()
    # 新しい active ticket + reviewed run を作成
    async with session_factory() as session:
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["reviewed-new"]
        )
    async with session_factory() as session:
        repo = TicketRepository(session)
        active = await repo.list_in_project(TENANT_1, PROJECT_ACTIVE)
        reviewed_ticket = str(active[0].id)
    async with session_factory() as session:
        reviewed = await bridge_run_create(
            session,
            tenant_id=TENANT_1,
            project_id=PROJECT_ACTIVE,
            ticket_id=reviewed_ticket,
            purpose="work",
        )
        reviewed_run_id = UUID(reviewed["run_id"])

    # 古い deleted-ticket-bound reviewer を指定 → reviewer actionable check で reject
    async with session_factory() as session:
        result = await bridge_delegation_review(
            session,
            tenant_id=TENANT_1,
            run_id=reviewed_run_id,
            reviewer_run_id=reviewer_run_id,
            decision="adopt",
            quality_score=0.9,
        )
        assert result.get("error") == "TicketNotActionableError"

    # approval_decided event は記録されていない
    async with session_factory() as session:
        decided = await session.execute(
            text(
                "SELECT count(*) FROM agent_run_events "
                "WHERE tenant_id = :tid AND run_id = :rid AND event_type = 'approval_decided'"
            ),
            {"tid": TENANT_1, "rid": reviewed_run_id},
        )
        assert decided.scalar_one() == 0


# --------- R16 (Codex adversarial): nested/recursive read path + delegation parent write ---------


async def _soft_delete_one_ticket(
    session_factory: async_sessionmaker[AsyncSession], project_id: UUID, ticket_id: str
) -> UUID:
    """特定 ticket 1 件だけを soft-delete する (bulk は全 active を消すため、graph 部分削除の構成用)。

    restore は ``restore_batch_in_project(tenant, project, batch)`` で行える batch_id を返す。
    """
    batch = uuid4()
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE tickets SET deleted_at = now(), deleted_batch_id = :b, "
                "deleted_by_actor_id = :a WHERE tenant_id = :t AND project_id = :p AND id = :tid"
            ),
            {"b": batch, "a": ACTOR_OWNER, "t": TENANT_1, "p": project_id, "tid": ticket_id},
        )
        await session.commit()
    return batch


async def _make_parent_child(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID, str, str]:
    """parent run (ticket A bound) + child run (ticket B bound、delegation) を作る。

    returns (parent_run_id, child_run_id, ticket_a_id, ticket_b_id)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["parent-t", "child-t"]
        )
    async with session_factory() as session:
        repo = TicketRepository(session)
        tickets = await repo.list_in_project(TENANT_1, PROJECT_ACTIVE)
        ticket_b = str(next(t.id for t in tickets if t.slug == "child-t"))
        ticket_a = str(next(t.id for t in tickets if t.slug == "parent-t"))
    async with session_factory() as session:
        parent = await bridge_run_create(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE,
            ticket_id=ticket_a, purpose="parent-work",
        )
        parent_run_id = UUID(parent["run_id"])
    async with session_factory() as session:
        child = await bridge_delegation_create(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE,
            parent_run_id=parent_run_id, ticket_id=ticket_b, purpose="child-work",
            role_id="implementer", task_spec={"goal": "x"}, sender_actor_id=ACTOR_OWNER,
        )
        assert "error" not in child, child
        child_run_id = UUID(child["child_run_id"])
    return parent_run_id, child_run_id, ticket_a, ticket_b


@pytestmark_db
@pytest.mark.asyncio
async def test_run_show_children_exclude_soft_deleted_ticket_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R16 #3): parent show の children も active-scope。soft-deleted
    ticket bound の child run を parent 経由で列挙させない (直接 show は not_found なのに親から漏れる迂回)。
    """
    parent_run_id, child_run_id, _ta, ticket_b = await _make_parent_child(session_factory)

    # 削除前: children に child が含まれる
    async with session_factory() as session:
        show = await bridge_run_show(session, tenant_id=TENANT_1, run_id=parent_run_id)
        assert {c["run_id"] for c in show["children"]} == {str(child_run_id)}

    # child の ticket だけ soft-delete
    batch = await _soft_delete_one_ticket(session_factory, PROJECT_ACTIVE, ticket_b)

    # parent は表示できる (ticket A active) が children から削除済 child が消える
    async with session_factory() as session:
        show = await bridge_run_show(session, tenant_id=TENANT_1, run_id=parent_run_id)
        assert show["run_id"] == str(parent_run_id)
        assert show["children"] == []

    # restore で child が戻る
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.restore_batch_in_project(TENANT_1, PROJECT_ACTIVE, batch)
        await session.commit()
    async with session_factory() as session:
        show = await bridge_run_show(session, tenant_id=TENANT_1, run_id=parent_run_id)
        assert {c["run_id"] for c in show["children"]} == {str(child_run_id)}


@pytestmark_db
@pytest.mark.asyncio
async def test_delegation_tree_excludes_soft_deleted_ticket_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R16 #1): delegation_tree の再帰 CTE も active-scope。削除済 child は
    tree から除外、削除済 root は not_found、restore で復帰 (run_show の active-scope を迂回させない)。
    """
    parent_run_id, child_run_id, ticket_a, ticket_b = await _make_parent_child(session_factory)

    # 削除前: tree に parent + child
    async with session_factory() as session:
        tree = await bridge_delegation_tree(session, tenant_id=TENANT_1, root_run_id=parent_run_id)
        ids = {n["run_id"] for n in tree["tree"]}
        assert ids == {str(parent_run_id), str(child_run_id)}

    # child の ticket だけ削除 → tree から child 除外 (parent は root のまま)
    await _soft_delete_one_ticket(session_factory, PROJECT_ACTIVE, ticket_b)
    async with session_factory() as session:
        tree = await bridge_delegation_tree(session, tenant_id=TENANT_1, root_run_id=parent_run_id)
        ids = {n["run_id"] for n in tree["tree"]}
        assert ids == {str(parent_run_id)}

    # parent の ticket も削除 → root 自体が消え not_found
    await _soft_delete_one_ticket(session_factory, PROJECT_ACTIVE, ticket_a)
    async with session_factory() as session:
        tree = await bridge_delegation_tree(session, tenant_id=TENANT_1, root_run_id=parent_run_id)
        assert tree.get("error") == "not_found"


@pytestmark_db
@pytest.mark.asyncio
async def test_delegation_create_rejects_deleted_ticket_parent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R16 #2): parent_run_id の run 自体が soft-deleted ticket に bind
    されていれば delegation_create は reject する。削除済 work item を delegation graph の制御点として
    復活させない write-path guard (child の新 ticket が active でも parent guard が先に効く)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["parent-old"]
        )
    parent_ticket = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    async with session_factory() as session:
        parent = await bridge_run_create(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE,
            ticket_id=parent_ticket, purpose="parent-work",
        )
        parent_run_id = UUID(parent["run_id"])
    # bulk soft-delete で parent の ticket を削除
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()
    # 新しい active ticket を作り、削除済 parent から delegation を試みる
    async with session_factory() as session:
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["child-new"]
        )
    async with session_factory() as session:
        repo = TicketRepository(session)
        new_ticket = str((await repo.list_in_project(TENANT_1, PROJECT_ACTIVE))[0].id)
    # R17: parent actionable 検証は chokepoint bridge_run_create に集約され、削除済 parent は
    # TicketNotActionableError を raise する (MCP wrapper が dict 化、ここでは bridge を直接呼ぶため raise)。
    async with session_factory() as session:
        with pytest.raises(TicketNotActionableError):
            await bridge_delegation_create(
                session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE,
                parent_run_id=parent_run_id, ticket_id=new_ticket, purpose="child-work",
                role_id="implementer", task_spec={"goal": "x"}, sender_actor_id=ACTOR_OWNER,
            )

    # child run も inter_agent_message も作られていない
    async with session_factory() as session:
        child_count = await session.execute(
            text(
                "SELECT count(*) FROM agent_runs WHERE tenant_id = :t AND parent_run_id = :p"
            ),
            {"t": TENANT_1, "p": parent_run_id},
        )
        assert child_count.scalar_one() == 0
        msg_count = await session.execute(
            text(
                "SELECT count(*) FROM inter_agent_messages "
                "WHERE tenant_id = :t AND parent_run_id = :p"
            ),
            {"t": TENANT_1, "p": parent_run_id},
        )
        assert msg_count.scalar_one() == 0


@pytestmark_db
@pytest.mark.asyncio
async def test_run_create_rejects_deleted_ticket_parent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R17 #1): parent guard は chokepoint bridge_run_create に集約。
    MCP run_create が parent_run_id を直接受けるため、削除済 ticket bound parent への child attach を
    bridge_run_create 自体で reject する (delegation_create の R16 guard 迂回を塞ぐ)。child ticket が
    active でも parent guard が効く。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["parent-old"]
        )
    parent_ticket = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    async with session_factory() as session:
        parent = await bridge_run_create(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE,
            ticket_id=parent_ticket, purpose="parent-work",
        )
        parent_run_id = UUID(parent["run_id"])
    # bulk soft-delete で parent ticket を削除、新 active ticket を用意
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()
    async with session_factory() as session:
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["child-new"]
        )
    async with session_factory() as session:
        repo = TicketRepository(session)
        new_ticket = str((await repo.list_in_project(TENANT_1, PROJECT_ACTIVE))[0].id)

    # bridge_run_create 直呼びでも 削除済 parent を reject (child ticket は active)
    async with session_factory() as session:
        with pytest.raises(TicketNotActionableError):
            await bridge_run_create(
                session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE,
                ticket_id=new_ticket, purpose="child-work", parent_run_id=parent_run_id,
            )

    # child run は作られていない
    async with session_factory() as session:
        child_count = await session.execute(
            text("SELECT count(*) FROM agent_runs WHERE tenant_id = :t AND parent_run_id = :p"),
            {"t": TENANT_1, "p": parent_run_id},
        )
        assert child_count.scalar_one() == 0


@pytestmark_db
@pytest.mark.asyncio
async def test_delegation_inbox_accept_reject_deleted_parent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R17 #2): parent ticket が delegation_create 後・accept 前に
    soft-delete された場合、child ticket が active でも inbox から message を除外し accept を reject する
    (削除済 work が queued message 経由で graph を進める timing 漏れを塞ぐ)。
    """
    parent_run_id, child_run_id, ticket_a, _tb = await _make_parent_child(session_factory)

    # 削除前: child の inbox に 1 message
    async with session_factory() as session:
        inbox = await bridge_delegation_inbox(session, tenant_id=TENANT_1, run_id=child_run_id)
        assert inbox["total"] == 1
        message_id = UUID(inbox["messages"][0]["id"])

    # parent の ticket だけ soft-delete (child ticket は active のまま)
    await _soft_delete_one_ticket(session_factory, PROJECT_ACTIVE, ticket_a)

    # inbox から message が除外される
    async with session_factory() as session:
        inbox = await bridge_delegation_inbox(session, tenant_id=TENANT_1, run_id=child_run_id)
        assert inbox["total"] == 0

    # accept は parent actionable 検証で reject、message は未消費・child は queued のまま
    async with session_factory() as session:
        result = await bridge_delegation_accept(
            session, tenant_id=TENANT_1, run_id=child_run_id, message_id=message_id
        )
        assert result.get("error") == "TicketNotActionableError"
    async with session_factory() as session:
        consumed = await session.execute(
            text(
                "SELECT consumed_at FROM inter_agent_messages WHERE tenant_id = :t AND id = :m"
            ),
            {"t": TENANT_1, "m": message_id},
        )
        assert consumed.scalar_one() is None
        status_row = await session.execute(
            text("SELECT status FROM agent_runs WHERE tenant_id = :t AND id = :r"),
            {"t": TENANT_1, "r": child_run_id},
        )
        assert status_row.scalar_one() == "queued"


# --------- R18 (Codex adversarial): approval trust boundary active-scope ---------


async def _create_ticket_approval(
    session_factory: async_sessionmaker[AsyncSession], ticket_id: str
) -> UUID:
    """ticket bound の pending approval (resource_ref=ticket:<uuid>) を作り approval_id を返す。"""
    async with session_factory() as session:
        created = await bridge_approval_request_create(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE,
            ticket_id=ticket_id, action_class="repo_write", requester_actor_id=ACTOR_OWNER,
        )
        return UUID(created["approval_id"])


@pytestmark_db
@pytest.mark.asyncio
async def test_approval_decide_rejects_soft_deleted_ticket(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R18, P0-active ship-block): bulk soft-delete 後の stale approval を
    approve できない。decide chokepoint (ApprovalDecisionService.approve) で bound ticket の active-scope を
    再検証し、削除済 work への human authorization 付与を 409 で fail-closed。approval は pending のまま
    (restore で再承認可能)。
    """
    from backend.app.api.approval_inbox import ApprovalDecideRequest, decide_approval
    from backend.app.services.policy.approval_active_scope import is_approval_target_actionable

    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["appr-1"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    approval_id = await _create_ticket_approval(session_factory, ticket_id)

    # soft-delete
    async with session_factory() as session:
        repo = TicketRepository(session)
        batch, _ = await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()

    # approve は 409 (stale: 削除済 ticket bound)。R18 guard は self-approval guard より先に走るため、
    # detail は active-scope (not actionable) を示す。
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await decide_approval(
                approval_id=approval_id,
                body=ApprovalDecideRequest(action="approve", rationale="x"),
                actor_id=ACTOR_OWNER, tenant_id=TENANT_1, session=session,
            )
        assert exc.value.status_code == 409
        assert "not actionable" in str(exc.value.detail)

    # approval は pending のまま (approved になっていない、削除済 work への authorization なし)
    async with session_factory() as session:
        st = await session.execute(
            text("SELECT status FROM approval_requests WHERE tenant_id = :t AND id = :a"),
            {"t": TENANT_1, "a": approval_id},
        )
        assert st.scalar_one() == "pending"

    # restore 後は guard が解け再び actionable (= approve 可能経路に戻る)。helper で直接検証
    # (実 approve は self-approval guard 上 human 別 actor が必要なため、ここでは active-scope 解除のみ確認)。
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.restore_batch_in_project(TENANT_1, PROJECT_ACTIVE, batch)
        await session.commit()
    async with session_factory() as session:
        assert await is_approval_target_actionable(
            session, tenant_id=TENANT_1, resource_ref=f"ticket:{ticket_id}"
        )


@pytestmark_db
@pytest.mark.asyncio
async def test_approval_list_detail_hide_soft_deleted_ticket(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R18): stale (削除済 ticket bound) approval を inbox list / detail から
    隠す (全 read path active-scope)。restore で再表示。非 ticket approval は対象外。
    """
    from backend.app.api.approval_inbox import get_approval_detail, list_pending_approvals

    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["appr-2"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    approval_id = await _create_ticket_approval(session_factory, ticket_id)

    # 削除前: list に 1 件、detail 取得可
    async with session_factory() as session:
        listed = await list_pending_approvals(tenant_id=TENANT_1, session=session)
        assert len(listed) == 1
        detail = await get_approval_detail(
            approval_id=approval_id, tenant_id=TENANT_1, session=session
        )
        assert str(detail.id) == str(approval_id)

    # soft-delete
    async with session_factory() as session:
        repo = TicketRepository(session)
        batch, _ = await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()

    # 削除後: list から除外、detail 404
    async with session_factory() as session:
        listed = await list_pending_approvals(tenant_id=TENANT_1, session=session)
        assert listed == []
        with pytest.raises(HTTPException) as exc:
            await get_approval_detail(
                approval_id=approval_id, tenant_id=TENANT_1, session=session
            )
        assert exc.value.status_code == 404

    # restore で再表示
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.restore_batch_in_project(TENANT_1, PROJECT_ACTIVE, batch)
        await session.commit()
    async with session_factory() as session:
        listed = await list_pending_approvals(tenant_id=TENANT_1, session=session)
        assert len(listed) == 1


@pytestmark_db
@pytest.mark.asyncio
async def test_mcp_approval_list_show_hide_soft_deleted_ticket(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R19 #2): MCP approval read path (bridge_approval_list /
    bridge_approval_show) も HTTP inbox と同じ active-scope。soft-deleted ticket bound な stale approval を
    AI agent に露出させない (list 除外 + show not_found)。restore で再表示。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["mcp-appr"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)
    approval_id = await _create_ticket_approval(session_factory, ticket_id)

    # 削除前: MCP list に 1 件、show 取得可
    async with session_factory() as session:
        listed = await bridge_approval_list(session, tenant_id=TENANT_1)
        assert {a["id"] for a in listed["approvals"]} == {str(approval_id)}
        shown = await bridge_approval_show(session, tenant_id=TENANT_1, approval_id=approval_id)
        assert shown["id"] == str(approval_id)

    # soft-delete
    async with session_factory() as session:
        repo = TicketRepository(session)
        batch, _ = await repo.bulk_soft_delete_in_project(
            TENANT_1, PROJECT_ACTIVE, expected_active_count=1, deleted_by_actor_id=ACTOR_OWNER
        )
        await session.commit()

    # 削除後: MCP list から除外、show は not_found
    async with session_factory() as session:
        listed = await bridge_approval_list(session, tenant_id=TENANT_1)
        assert listed["approvals"] == []
        shown = await bridge_approval_show(session, tenant_id=TENANT_1, approval_id=approval_id)
        assert shown.get("error") == "not_found"

    # restore で再表示
    async with session_factory() as session:
        repo = TicketRepository(session)
        await repo.restore_batch_in_project(TENANT_1, PROJECT_ACTIVE, batch)
        await session.commit()
    async with session_factory() as session:
        listed = await bridge_approval_list(session, tenant_id=TENANT_1)
        assert {a["id"] for a in listed["approvals"]} == {str(approval_id)}


@pytestmark_db
@pytest.mark.asyncio
async def test_approve_guard_acquires_project_lock(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R19 #1, TOCTOU): approve guard は bound ticket の project row を
    FOR UPDATE lock し、bulk_soft_delete / archive と直列化する。別 session が project lock を保持する間、
    locked guard は block する (非ロック SELECT だと TOCTOU で削除済 work を approve できた)。
    """
    from backend.app.services.policy.approval_active_scope import (
        assert_approval_target_actionable_locked,
    )

    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["lock-appr"]
        )
    ticket_id = await _first_ticket_id(session_factory, PROJECT_ACTIVE)

    # session A が project row を FOR UPDATE lock (commit せず保持)。
    locker = session_factory()
    lock_session = await locker.__aenter__()
    try:
        await lock_session.execute(
            text("SELECT id FROM projects WHERE tenant_id = :t AND id = :p FOR UPDATE"),
            {"t": TENANT_1, "p": PROJECT_ACTIVE},
        )
        # session B: locked guard は同 project lock 待ちで block → wait_for が TimeoutError。
        async with session_factory() as guarded:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    assert_approval_target_actionable_locked(
                        guarded, tenant_id=TENANT_1, resource_ref=f"ticket:{ticket_id}"
                    ),
                    timeout=2.0,
                )
    finally:
        await locker.__aexit__(None, None, None)

    # lock 解放後は guard が通る (ticket active)。
    async with session_factory() as session:
        await assert_approval_target_actionable_locked(
            session, tenant_id=TENANT_1, resource_ref=f"ticket:{ticket_id}"
        )


@pytestmark_db
@pytest.mark.asyncio
async def test_delegation_create_serializes_under_project_lock(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R20): bridge_delegation_create は child run 作成 (commit=False) と
    inter_agent_messages INSERT を **同一 project lock 下の 1 transaction** で行う。別 session が project
    lock を保持する間 delegation_create は block する (内部 commit で lock を手放すと、削除/凍結後に message
    を書ける TOCTOU になる)。lock 解放後は成功し child run + message が atomic に commit される。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)
        await _seed_tickets(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, slugs=["dl-parent", "dl-child"]
        )
    async with session_factory() as session:
        repo = TicketRepository(session)
        tickets = await repo.list_in_project(TENANT_1, PROJECT_ACTIVE)
        ticket_parent = str(next(t.id for t in tickets if t.slug == "dl-parent"))
        ticket_child = str(next(t.id for t in tickets if t.slug == "dl-child"))
    async with session_factory() as session:
        parent = await bridge_run_create(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE,
            ticket_id=ticket_parent, purpose="parent",
        )
        parent_run_id = UUID(parent["run_id"])

    # session A が project lock を保持 → delegation_create (session B) は block。
    locker = session_factory()
    lock_session = await locker.__aenter__()
    try:
        await lock_session.execute(
            text("SELECT id FROM projects WHERE tenant_id = :t AND id = :p FOR UPDATE"),
            {"t": TENANT_1, "p": PROJECT_ACTIVE},
        )
        async with session_factory() as guarded:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    bridge_delegation_create(
                        guarded, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE,
                        parent_run_id=parent_run_id, ticket_id=ticket_child, purpose="child",
                        role_id="implementer", task_spec={"g": "x"}, sender_actor_id=ACTOR_OWNER,
                    ),
                    timeout=2.0,
                )
    finally:
        await locker.__aexit__(None, None, None)

    # lock 解放後は成功し child run + message が atomic に存在する。
    async with session_factory() as session:
        created = await bridge_delegation_create(
            session, tenant_id=TENANT_1, project_id=PROJECT_ACTIVE,
            parent_run_id=parent_run_id, ticket_id=ticket_child, purpose="child",
            role_id="implementer", task_spec={"g": "x"}, sender_actor_id=ACTOR_OWNER,
        )
        assert "error" not in created, created
        child_run_id = created["child_run_id"]
    async with session_factory() as session:
        run_cnt = await session.execute(
            text("SELECT count(*) FROM agent_runs WHERE tenant_id = :t AND id = :r"),
            {"t": TENANT_1, "r": child_run_id},
        )
        assert run_cnt.scalar_one() == 1
        msg_cnt = await session.execute(
            text(
                "SELECT count(*) FROM inter_agent_messages "
                "WHERE tenant_id = :t AND child_run_id = :r"
            ),
            {"t": TENANT_1, "r": child_run_id},
        )
        assert msg_cnt.scalar_one() == 1


@pytestmark_db
@pytest.mark.asyncio
async def test_delegation_inbox_accept_excludes_archived_project(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R22): archived project (project.status<>'active'、ticket は
    soft-delete されない別 state) の delegation も inbox から除外する。active project で delegation を作成後
    Q-4 archive すると、R17 の soft-delete filter (deleted_at のみ) では除外されず stale queued message が
    露出していた。inbox total=0 + accept は ProjectArchivedError で未消費。
    """
    parent_run_id, child_run_id, _ta, _tb = await _make_parent_child(session_factory)

    # archive 前: inbox に 1 message
    async with session_factory() as session:
        inbox = await bridge_delegation_inbox(session, tenant_id=TENANT_1, run_id=child_run_id)
        assert inbox["total"] == 1
        message_id = UUID(inbox["messages"][0]["id"])

    # project を archive (ticket は soft-delete されない)
    async with session_factory() as session:
        service = ProjectArchiveService(session)
        await service.set_archived(
            tenant_id=TENANT_1, project_id=PROJECT_ACTIVE, archived=True, expected_status="active"
        )
        await session.commit()

    # inbox から除外 (archive freeze 後の stale delegation read を塞ぐ)
    async with session_factory() as session:
        inbox = await bridge_delegation_inbox(session, tenant_id=TENANT_1, run_id=child_run_id)
        assert inbox["total"] == 0

    # accept は ProjectArchivedError で reject、message 未消費・child は queued のまま
    async with session_factory() as session:
        result = await bridge_delegation_accept(
            session, tenant_id=TENANT_1, run_id=child_run_id, message_id=message_id
        )
        assert result.get("error") == "ProjectArchivedError"
    async with session_factory() as session:
        consumed = await session.execute(
            text("SELECT consumed_at FROM inter_agent_messages WHERE tenant_id = :t AND id = :m"),
            {"t": TENANT_1, "m": message_id},
        )
        assert consumed.scalar_one() is None
        status_row = await session.execute(
            text("SELECT status FROM agent_runs WHERE tenant_id = :t AND id = :r"),
            {"t": TENANT_1, "r": child_run_id},
        )
        assert status_row.scalar_one() == "queued"


@pytestmark_db
@pytest.mark.asyncio
async def test_delegation_inbox_accept_reject_deleted_child(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex adversarial R23): inbox の宛先である child (receiver) run **自体** の ticket が
    soft-deleted なら、その work-queue は frozen なので message を露出しない。R17/R22 filter は archived +
    parent/sender の soft-delete を見ていたが child ticket を見ておらず、parent が active なら stale message
    が露出していた。inbox total=0 + accept は TicketNotActionableError で未消費。
    """
    parent_run_id, child_run_id, _ta, ticket_child = await _make_parent_child(session_factory)

    # 削除前: inbox に 1 message
    async with session_factory() as session:
        inbox = await bridge_delegation_inbox(session, tenant_id=TENANT_1, run_id=child_run_id)
        assert inbox["total"] == 1
        message_id = UUID(inbox["messages"][0]["id"])

    # child の ticket **だけ** soft-delete (parent ticket は active のまま)
    await _soft_delete_one_ticket(session_factory, PROJECT_ACTIVE, ticket_child)

    # inbox から除外 (parent active でも child frozen なら work-queue に出さない)
    async with session_factory() as session:
        inbox = await bridge_delegation_inbox(session, tenant_id=TENANT_1, run_id=child_run_id)
        assert inbox["total"] == 0

    # accept は child actionable 検証で reject、message 未消費・child は queued のまま
    async with session_factory() as session:
        result = await bridge_delegation_accept(
            session, tenant_id=TENANT_1, run_id=child_run_id, message_id=message_id
        )
        assert result.get("error") == "TicketNotActionableError"
    async with session_factory() as session:
        consumed = await session.execute(
            text("SELECT consumed_at FROM inter_agent_messages WHERE tenant_id = :t AND id = :m"),
            {"t": TENANT_1, "m": message_id},
        )
        assert consumed.scalar_one() is None


# --------- R26 (Codex App PR review): import 404 + delegation_submit parent guard ---------


@pytestmark_db
@pytest.mark.asyncio
async def test_import_nonexistent_project_returns_404(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex App PR review): 存在しない project への import は dry_run / 実行とも 404。
    `assert_project_active` は missing project で no-op だったため、dry_run が valid を返し実 import が
    ticket FK 違反まで進んで誤った 409 を返していた。bulk-delete と整合する 404 を slug/dry_run より前に返す。
    """
    missing_project = UUID("00000000-0000-4000-8000-0000000dd0ee")
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed_base(session)

    # dry_run でも 404 (preview を返さない)
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await import_tickets_endpoint(
                project_id=missing_project,
                payload=ImportTicketsRequest(
                    tickets=[TicketImportItem(slug="x-1", title="x")], dry_run=True
                ),
                owner_actor_id=ACTOR_OWNER, tenant_id=TENANT_1, session=session,
            )
        assert exc.value.status_code == 404

    # 実 import も 404 (FK 違反の 409 ではない)
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await import_tickets_endpoint(
                project_id=missing_project,
                payload=ImportTicketsRequest(
                    tickets=[TicketImportItem(slug="x-2", title="x")]
                ),
                owner_actor_id=ACTOR_OWNER, tenant_id=TENANT_1, session=session,
            )
        assert exc.value.status_code == 404


@pytestmark_db
@pytest.mark.asyncio
async def test_delegation_submit_rejects_deleted_parent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION (Codex App PR review): delegation_submit は child だけでなく **parent run** も actionable
    か検証する。parent ticket が delegation 後に soft-delete された場合、child active のまま result message を
    削除済 parent に提出できてしまう漏れ (accept/review と同じ parent active-scope) を塞ぐ。reject 時は
    child status 不変 + result message 未生成。
    """
    parent_run_id, child_run_id, ticket_parent, _tc = await _make_parent_child(session_factory)

    # parent の ticket **だけ** soft-delete (child ticket は active)
    await _soft_delete_one_ticket(session_factory, PROJECT_ACTIVE, ticket_parent)

    # submit は parent actionable 検証で reject
    async with session_factory() as session:
        result = await bridge_delegation_submit(
            session, tenant_id=TENANT_1, run_id=child_run_id, parent_run_id=parent_run_id,
            project_id=PROJECT_ACTIVE, result_status="completed", result_summary="done",
            result_spec={"r": "x"}, actor_id=ACTOR_OWNER,
        )
        assert result.get("error") == "TicketNotActionableError"

    # child status 不変 (queued) + result message 未生成
    async with session_factory() as session:
        st = await session.execute(
            text("SELECT status FROM agent_runs WHERE tenant_id = :t AND id = :r"),
            {"t": TENANT_1, "r": child_run_id},
        )
        assert st.scalar_one() == "queued"
        msgs = await session.execute(
            text(
                "SELECT count(*) FROM inter_agent_messages "
                "WHERE tenant_id = :t AND artifact_ref LIKE :pat"
            ),
            {"t": TENANT_1, "pat": f"result:{child_run_id}:%"},
        )
        assert msgs.scalar_one() == 0
