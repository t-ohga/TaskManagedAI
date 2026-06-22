"""SP-PHASE1 B5b: MCP mutating bridge emergency-stop latch gate (ADR-00048 §B-2)。

centralize した deny-list / allow-list の網羅 negative test:
- **drift guard (no-DB)**: deny-list registry が、実際に ``assert_bridge_not_emergency_stopped`` を呼ぶ
  bridge 関数集合と **exact-set 一致** (AST 解析)。deny-list と allow-list が disjoint。
- **deny-list engaged-deny (DB-gated)**: latch engaged 中、各 deny-list mutating bridge が
  ``EmergencyStopEngagedError`` を raise する。
- **allow-list engaged-allow (DB-gated)**: latch engaged 中も read/status/list/run_cancel が通る
  (kill 経路を塞がない)。
- **cleared 後 allow (DB-gated)**: clear すると mutating bridge が再び通る。

DB-gated test は TASKHUB_DISABLE_KEYRING=1 + TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL。
"""

from __future__ import annotations

import ast
import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import backend.app.mcp.api_bridge as api_bridge
from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.mcp.api_bridge import (
    MCP_BRIDGE_ALLOW_LIST,
    MCP_MUTATING_BRIDGE_DENY_LIST,
)
from backend.app.services.superintendent.emergency_stop import (
    EmergencyStopEngagedError,
    EmergencyStopService,
)

_API_BRIDGE_PATH = Path(api_bridge.__file__)


# --------------------------------------------------------------------------- #
# drift guard (no-DB): registry == gated functions, deny/allow disjoint
# --------------------------------------------------------------------------- #


def _gated_bridge_functions() -> frozenset[str]:
    """``assert_bridge_not_emergency_stopped`` を body に持つ bridge_* 関数集合を AST で抽出する。"""
    src = _API_BRIDGE_PATH.read_text()
    tree = ast.parse(src)
    gated: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("bridge_"):
            body_src = ast.get_source_segment(src, node) or ""
            if "assert_bridge_not_emergency_stopped" in body_src:
                gated.add(node.name)
    return frozenset(gated)


def test_deny_list_matches_gated_functions_exact_set() -> None:
    """deny-list registry == 実際に gate を呼ぶ関数集合 (config と実装の drift 防止)。"""
    gated = _gated_bridge_functions()
    assert MCP_MUTATING_BRIDGE_DENY_LIST == gated, (
        f"deny-list drift: missing={MCP_MUTATING_BRIDGE_DENY_LIST - gated}, "
        f"extra={gated - MCP_MUTATING_BRIDGE_DENY_LIST}"
    )


def test_deny_and_allow_lists_are_disjoint() -> None:
    assert MCP_MUTATING_BRIDGE_DENY_LIST.isdisjoint(MCP_BRIDGE_ALLOW_LIST)


def test_kill_path_tools_are_allow_listed() -> None:
    """kill 経路 (run_cancel) と可視化 (read/list/status) は allow-list (engaged 中も通す)。"""
    assert "bridge_run_cancel" in MCP_BRIDGE_ALLOW_LIST
    assert "bridge_run_show" in MCP_BRIDGE_ALLOW_LIST
    assert "bridge_run_list" in MCP_BRIDGE_ALLOW_LIST
    # 進行系は deny-list (engaged 中 deny)。
    assert "bridge_run_update" in MCP_MUTATING_BRIDGE_DENY_LIST
    assert "bridge_run_create" in MCP_MUTATING_BRIDGE_DENY_LIST
    # adversarial HIGH-1: run_cost は mutating write (cost/KPI 進行) のため deny-list。
    assert "bridge_run_cost" in MCP_MUTATING_BRIDGE_DENY_LIST
    assert "bridge_run_cost" not in MCP_BRIDGE_ALLOW_LIST


def test_allow_list_bridges_do_not_call_gate() -> None:
    """allow-list bridge は gate を呼ばない (read/kill 経路を engaged 中も通す)。"""
    gated = _gated_bridge_functions()
    assert MCP_BRIDGE_ALLOW_LIST.isdisjoint(gated)


# allow-list semantics guard: drift guard (deny-list == gated-functions) は tautology で、mutating tool が
# 誤って allow-list に入った場合 (gate を呼ばない = engaged 中も通る) を検知できない。allow-list の各 bridge が
# (a) session.commit() を呼ばず、かつ (b) AgentRun の cost/status 列を UPDATE しない (= 真に read/kill 経路)
# ことを AST で assert し、将来 mutating tool が silently allow-list 入りするのを防ぐ。
# kill-aligned な write 例外 (cost/status 進行ではない停止/取り下げ) は明示 allowlist + rationale doc。
_ALLOW_LIST_WRITE_RATIONALE: dict[str, str] = {
    # run_cancel / delegation_cancel は kill/取り下げ整合 (作業を進める write ではなく止める write)。
    # 進行・cost・KPI を進めないため engaged 中も通すのが正 (kill 経路を塞がない)。
    "bridge_run_cancel": "kill 経路: 既存 run を停止する (進行/cost を進めない)。",
    "bridge_delegation_cancel": "取り下げ: delegation を cancel する (進行/cost を進めない)。",
}
# AgentRun の進行/cost を表す書込列 (allow-list bridge がこれらを UPDATE していたら work-advance bypass)。
_FORBIDDEN_ALLOW_LIST_WRITE_ATTRS = frozenset(
    {"cost_usd", "tokens_input", "tokens_output", "status", "blocked_reason"}
)


def _bridge_function_nodes() -> dict[str, ast.AsyncFunctionDef]:
    src = _API_BRIDGE_PATH.read_text()
    tree = ast.parse(src)
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("bridge_")
    }


def _calls_session_commit(node: ast.AST) -> bool:
    """body 内に ``session.commit()`` 呼び出しがあるか (AST)。"""
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "commit"
            and isinstance(sub.func.value, ast.Name)
            and sub.func.value.id == "session"
        ):
            return True
    return False


def _writes_agentrun_progress_attr(node: ast.AST) -> set[str]:
    """body 内に ``<obj>.<attr> = ...`` で進行/cost 列を書く代入があるか (AST、属性名のみ heuristic)。"""
    hits: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                if isinstance(tgt, ast.Attribute) and tgt.attr in _FORBIDDEN_ALLOW_LIST_WRITE_ATTRS:
                    hits.add(tgt.attr)
    return hits


def test_allow_list_bridges_have_no_mutating_writes() -> None:
    """allow-list の bridge は AgentRun cost/status 列を書かず commit しない (mutating tool の混入防止)。

    deny-list==gated drift guard は tautology のため、本 test が allow-list semantics を独立に enforce する。
    kill-aligned write (run_cancel / delegation_cancel) は ``_ALLOW_LIST_WRITE_RATIONALE`` で明示許可する。
    """
    nodes = _bridge_function_nodes()
    offenders: dict[str, str] = {}
    for name in MCP_BRIDGE_ALLOW_LIST:
        node = nodes.get(name)
        if node is None:
            continue  # AST に無い (別 module 等) は本 test の対象外。
        progress_writes = _writes_agentrun_progress_attr(node)
        commits = _calls_session_commit(node)
        if not progress_writes and not commits:
            continue
        # write/commit がある場合は kill-aligned rationale が必須。
        if name not in _ALLOW_LIST_WRITE_RATIONALE:
            offenders[name] = (
                f"writes={sorted(progress_writes)} commit={commits} "
                "(mutating tool は deny-list へ移すか kill rationale を追記すること)"
            )
        else:
            # rationale 付きでも AgentRun の cost 列 (進行) を書いていたら NG (kill は status 変更のみ可)。
            forbidden_cost = progress_writes & {"cost_usd", "tokens_input", "tokens_output"}
            if forbidden_cost:
                offenders[name] = (
                    f"kill-aligned だが cost 列を書いている: {sorted(forbidden_cost)}"
                )
    assert not offenders, f"allow-list mutating drift: {offenders}"


# --------------------------------------------------------------------------- #
# DB-gated: engaged deny / cleared allow / allow-list engaged-allow
# --------------------------------------------------------------------------- #

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ONE = 1
TENANT_TWO = 2
# bridge_run_create は run_queued event を DEFAULT_SUPERINTENDENT_ACTOR_ID で attribution するため、
# tenant 1 の owner を同 id (= seed_initial の human:default) にして event FK を満たす。
ACTOR_OWNER_1 = UUID("00000000-0000-4000-8000-000000000001")
ACTOR_OWNER_2 = UUID("00000000-0000-4000-8000-0000000d6003")
WORKSPACE_1 = UUID("00000000-0000-4000-8000-0000000d6010")
WORKSPACE_2 = UUID("00000000-0000-4000-8000-0000000d6011")
PROJECT_1 = UUID("00000000-0000-4000-8000-0000000d6020")
PROJECT_2 = UUID("00000000-0000-4000-8000-0000000d6021")

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
        dev_login_cookie_secret="test-cookie-secret-for-bridge-latch-gate",
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
        raise AssertionError("bridge latch gate tests require PostgreSQL.") from exc
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


async def _reset(session: AsyncSession) -> None:
    await session.execute(
        text(
            "truncate superintendent_emergency_stops, agent_run_events, agent_runs, "
            "inter_agent_messages, notification_events, approval_requests, "
            "ticket_relations, tickets, audit_events, projects, workspaces, actors, "
            "tenants restart identity cascade"
        )
    )
    await session.commit()


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text(
            "insert into tenants (id, name, metadata) values "
            "(1, 'tenant-one', '{\"rls_ready\": true}'::jsonb),"
            "(2, 'tenant-two', '{\"rls_ready\": true}'::jsonb)"
        )
    )
    # ACTOR_OWNER_1 (= DEFAULT_SUPERINTENDENT_ACTOR_ID) は tenant 1 の human owner で、tenant 1 の
    # bridge_run_create が run_queued event を本 id で attribution する (event FK を満たす)。
    # actors.id は単一 PK のため tenant 2 で同 id は再利用できない。tenant 2 の bridge_run_create には
    # ACTOR_OWNER_2 を明示 actor_id として渡し、event を tenant 2 の actor へ attribution する。
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values
              (:o1, 1, 'human', 'human:default', 'Owner1', '{"rls_ready": true}'::jsonb),
              (:o2, 2, 'human', 'human:default', 'Owner2', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"o1": ACTOR_OWNER_1, "o2": ACTOR_OWNER_2},
    )
    await session.execute(
        text(
            "insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata) values "
            "(:w1, 1, 'ws1', 'ws1', :o1, '{\"rls_ready\": true}'::jsonb),"
            "(:w2, 2, 'ws2', 'ws2', :o2, '{\"rls_ready\": true}'::jsonb)"
        ),
        {"w1": WORKSPACE_1, "o1": ACTOR_OWNER_1, "w2": WORKSPACE_2, "o2": ACTOR_OWNER_2},
    )
    await session.execute(
        text(
            "insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata) values "
            "(:p1, 1, :w1, 'p1', 'p1', 'active', '{\"rls_ready\": true}'::jsonb),"
            "(:p2, 2, :w2, 'p2', 'p2', 'active', '{\"rls_ready\": true}'::jsonb)"
        ),
        {"p1": PROJECT_1, "w1": WORKSPACE_1, "p2": PROJECT_2, "w2": WORKSPACE_2},
    )
    await session.commit()


async def _make_ticket(
    session: AsyncSession, *, tenant_id: int, project_id: UUID, slug: str
) -> UUID:
    tid = uuid4()
    await session.execute(
        text(
            "insert into tickets (id, tenant_id, project_id, slug, title, status, "
            "created_by_actor_id, metadata) values "
            "(:i, :t, :p, :slug, :title, 'open', :a, '{\"rls_ready\": true}'::jsonb)"
        ),
        {
            "i": tid,
            "t": tenant_id,
            "p": project_id,
            "slug": slug,
            "title": f"ticket-{slug}",
            "a": ACTOR_OWNER_1 if tenant_id == 1 else ACTOR_OWNER_2,
        },
    )
    await session.commit()
    return tid


async def _engage(session: AsyncSession, tenant_id: int, actor_id: UUID) -> int:
    result = await EmergencyStopService(session).engage(
        tenant_id=tenant_id, operator_actor_id=actor_id
    )
    await session.commit()
    return result.generation


@pytest.mark.asyncio
async def test_deny_list_bridges_deny_when_engaged(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """latch engaged 中、代表的な deny-list mutating bridge が EmergencyStopEngagedError を raise する。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        ticket_id = await _make_ticket(session, tenant_id=1, project_id=PROJECT_1, slug="t1")

    async with session_factory() as session:
        await _engage(session, 1, ACTOR_OWNER_1)

    # 代表 deny-list bridge を engaged 中に呼ぶ → 全件 EmergencyStopEngagedError。
    async with session_factory() as session:
        with pytest.raises(EmergencyStopEngagedError):
            await api_bridge.bridge_run_create(
                session,
                tenant_id=1,
                project_id=PROJECT_1,
                ticket_id=str(ticket_id),
                purpose="p",
            )
    async with session_factory() as session:
        with pytest.raises(EmergencyStopEngagedError):
            await api_bridge.bridge_ticket_create(
                session, tenant_id=1, project_id=PROJECT_1, title="x"
            )
    async with session_factory() as session:
        with pytest.raises(EmergencyStopEngagedError):
            await api_bridge.bridge_ticket_comment(
                session,
                tenant_id=1,
                project_id=PROJECT_1,
                ticket_id=ticket_id,
                message="m",
                actor_id=ACTOR_OWNER_1,
            )
    async with session_factory() as session:
        with pytest.raises(EmergencyStopEngagedError):
            await api_bridge.bridge_approval_request_create(
                session,
                tenant_id=1,
                project_id=PROJECT_1,
                ticket_id=str(ticket_id),
                action_class="task_write",
                requester_actor_id=ACTOR_OWNER_1,
            )
    async with session_factory() as session:
        with pytest.raises(EmergencyStopEngagedError):
            await api_bridge.bridge_delegation_accept(
                session, tenant_id=1, run_id=uuid4(), message_id=uuid4()
            )


@pytest.mark.asyncio
async def test_allow_list_bridges_allow_when_engaged(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """latch engaged 中も read/list/status と run_cancel は通る (kill 経路を塞がない)。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        await _make_ticket(session, tenant_id=1, project_id=PROJECT_1, slug="t-allow")

    async with session_factory() as session:
        await _engage(session, 1, ACTOR_OWNER_1)

    # read/list は engaged 中も raise しない。
    async with session_factory() as session:
        res = await api_bridge.bridge_ticket_list(
            session, tenant_id=1, project_id=PROJECT_1
        )
        assert "tickets" in res or "error" not in res
    async with session_factory() as session:
        res = await api_bridge.bridge_run_list(
            session, tenant_id=1, project_id=PROJECT_1
        )
        assert isinstance(res, dict)
    async with session_factory() as session:
        res = await api_bridge.bridge_project_list(session, tenant_id=1)
        assert isinstance(res, dict)
    # run_cancel (kill 経路): 不在 run でも latch gate で deny されず not_found を返す。
    async with session_factory() as session:
        res = await api_bridge.bridge_run_cancel(session, tenant_id=1, run_id=uuid4())
        assert res.get("error") == "not_found"


@pytest.mark.asyncio
async def test_deny_list_bridges_allow_after_clear(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """clear 後は deny-list mutating bridge が再び通る (run create 成功)。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        ticket_id = await _make_ticket(
            session, tenant_id=1, project_id=PROJECT_1, slug="t-clear"
        )

    async with session_factory() as session:
        generation = await _engage(session, 1, ACTOR_OWNER_1)

    # engaged 中は deny。
    async with session_factory() as session:
        with pytest.raises(EmergencyStopEngagedError):
            await api_bridge.bridge_run_create(
                session, tenant_id=1, project_id=PROJECT_1,
                ticket_id=str(ticket_id), purpose="p",
            )

    # clear。
    async with session_factory() as session:
        await EmergencyStopService(session).clear(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1, expected_generation=generation
        )
        await session.commit()

    # cleared 後は run_create 成功。
    async with session_factory() as session:
        res = await api_bridge.bridge_run_create(
            session, tenant_id=1, project_id=PROJECT_1,
            ticket_id=str(ticket_id), purpose="p",
        )
        assert res.get("run_id")


@pytest.mark.asyncio
async def test_bridge_run_cost_denies_when_engaged_and_allows_after_clear(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """adversarial HIGH-1: bridge_run_cost は engaged 中 deny (mutating write)、clear 後は通る。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        ticket_id = await _make_ticket(
            session, tenant_id=1, project_id=PROJECT_1, slug="t-cost"
        )

    # 非 engaged で run を作る (queued = 非 terminal・actionable、production run)。
    async with session_factory() as session:
        created = await api_bridge.bridge_run_create(
            session, tenant_id=1, project_id=PROJECT_1,
            ticket_id=str(ticket_id), purpose="p",
        )
        run_id = UUID(created["run_id"])

    async with session_factory() as session:
        generation = await _engage(session, 1, ACTOR_OWNER_1)

    # engaged 中: bridge_run_cost は EmergencyStopEngagedError を raise (cost/KPI 進行を deny)。
    async with session_factory() as session:
        with pytest.raises(EmergencyStopEngagedError):
            await api_bridge.bridge_run_cost(
                session, tenant_id=1, run_id=run_id,
                cost_usd=1.23, tokens_input=10, tokens_output=20,
            )

    # cost が書かれていないこと (mutating write が gate で止まった)。
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "select coalesce(tokens_input, 0) + coalesce(tokens_output, 0) "
                    "from agent_runs where id = :r"
                ),
                {"r": run_id},
            )
        ).scalar_one()
        assert int(row or 0) == 0

    # clear。
    async with session_factory() as session:
        await EmergencyStopService(session).clear(
            tenant_id=1, operator_actor_id=ACTOR_OWNER_1, expected_generation=generation
        )
        await session.commit()

    # cleared 後は bridge_run_cost が通る (cost 更新成功)。
    async with session_factory() as session:
        res = await api_bridge.bridge_run_cost(
            session, tenant_id=1, run_id=run_id,
            cost_usd=1.23, tokens_input=10, tokens_output=20,
        )
        assert res.get("run_id") == str(run_id)
        assert res.get("tokens_input") == 10


@pytest.mark.asyncio
async def test_bridge_gate_cross_tenant_non_interference(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """tenant 1 engage で tenant 1 bridge は deny、tenant 2 bridge は allow (isolation)。"""
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        t1_ticket = await _make_ticket(session, tenant_id=1, project_id=PROJECT_1, slug="t1x")
        t2_ticket = await _make_ticket(session, tenant_id=2, project_id=PROJECT_2, slug="t2x")

    async with session_factory() as session:
        await _engage(session, 1, ACTOR_OWNER_1)

    # tenant 1: deny。
    async with session_factory() as session:
        with pytest.raises(EmergencyStopEngagedError):
            await api_bridge.bridge_run_create(
                session, tenant_id=1, project_id=PROJECT_1,
                ticket_id=str(t1_ticket), purpose="p",
            )
    # tenant 2: allow (engage は tenant-scoped)。actor_id は tenant 2 の actor を明示
    # (DEFAULT_SUPERINTENDENT_ACTOR_ID は tenant 1 の単一 PK actor のため tenant 2 では使えない)。
    async with session_factory() as session:
        res = await api_bridge.bridge_run_create(
            session, tenant_id=2, project_id=PROJECT_2,
            ticket_id=str(t2_ticket), purpose="p", actor_id=ACTOR_OWNER_2,
        )
        assert res.get("run_id")
