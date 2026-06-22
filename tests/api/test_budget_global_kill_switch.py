"""SP-PHASE1 B6: budget global kill-switch endpoints (ADR-00048 §A-8) の route + owner gate test。

検証:
- owner session cookie で engage → status engaged=true / clear → status engaged=false の roundtrip。
- find-or-create: active global budget が無くても engage が global budget を作成し flag を set。
- engage が autonomy policy engine の OR 評価 (global_kill_switch) を駆動できる状態を作る (DB 上 flag 確認)。
- cookie 無し request は engage/clear/status とも 401/403 (fail-closed、owner gate)。
- response に raw secret / token を含まない。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.api.approval_inbox import get_db_session
from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.main import create_app
from backend.app.middleware.dev_actor import (
    DEV_SESSION_COOKIE_NAME,
    create_signed_session_cookie,
)
from backend.app.seeds.initial import DEFAULT_ACTOR_ID

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_COOKIE_SECRET = "test-cookie-secret-for-budget-kill-switch"

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
        dev_login_cookie_secret=_COOKIE_SECRET,
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
        raise AssertionError("budget kill-switch tests require PostgreSQL.") from exc
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
        text("truncate budgets, audit_events, actors, tenants restart identity cascade")
    )
    await session.commit()


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text(
            "insert into tenants (id, name, metadata) values "
            "(1, 'tenant-one', '{\"rls_ready\": true}'::jsonb)"
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:own, 1, 'human', 'human:default', 'Owner', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"own": DEFAULT_ACTOR_ID},
    )
    await session.commit()


def _build_app(
    session_factory: async_sessionmaker[AsyncSession],
) -> object:
    app = create_app(_integration_settings())

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_session
    return app


@pytest.mark.asyncio
async def test_engage_status_clear_roundtrip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    app = _build_app(session_factory)
    cookie_value, _expires = create_signed_session_cookie(secret=_COOKIE_SECRET)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={DEV_SESSION_COOKIE_NAME: cookie_value},
    ) as client:
        # 未設定: engaged=false / budget_id=null
        status0 = await client.get("/api/v1/budget/global-kill-switch")
        assert status0.status_code == 200
        assert status0.json() == {"engaged": False, "budget_id": None}

        # engage: find-or-create global budget + flag set
        engage = await client.post("/api/v1/budget/global-kill-switch")
        assert engage.status_code == 200
        engage_payload = engage.json()
        assert engage_payload["engaged"] is True
        budget_id = engage_payload["budget_id"]
        assert isinstance(budget_id, str)

        # status: engaged
        status1 = await client.get("/api/v1/budget/global-kill-switch")
        assert status1.json() == {"engaged": True, "budget_id": budget_id}

        # clear
        clear = await client.post("/api/v1/budget/global-kill-switch/clear")
        assert clear.status_code == 200
        assert clear.json()["engaged"] is False

        status2 = await client.get("/api/v1/budget/global-kill-switch")
        assert status2.json()["engaged"] is False

    # DB 上 global budget が 1 件 (再 engage で重複しない) + flag が false に戻ったことを確認。
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "select global_kill_switch from budgets "
                    "where tenant_id = 1 and level = 'global' and active = true"
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].global_kill_switch is False


@pytest.mark.asyncio
async def test_routes_reject_no_cookie(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        engage = await client.post("/api/v1/budget/global-kill-switch")
        clear = await client.post("/api/v1/budget/global-kill-switch/clear")
        status_resp = await client.get("/api/v1/budget/global-kill-switch")
    assert engage.status_code in (401, 403)
    assert clear.status_code in (401, 403)
    assert status_resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_response_has_no_secret_or_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    app = _build_app(session_factory)
    cookie_value, _expires = create_signed_session_cookie(secret=_COOKIE_SECRET)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={DEV_SESSION_COOKIE_NAME: cookie_value},
    ) as client:
        engage = await client.post("/api/v1/budget/global-kill-switch")
    assert "token" not in engage.text.lower()
    assert "secret" not in engage.text.lower()


def test_budget_kill_switch_routes_wired_to_operator_gate() -> None:
    """B6 adversarial LOW (defense-in-depth): budget global-kill-switch の 3 route が
    ``require_emergency_stop_operator`` (authenticated + actor_type='human' + owner、fail-closed) に
    依存し続けることを wiring drift guard する。実 authz enforcement は本 gate dependency 側
    (``test_emergency_stop_operator_gate.py::test_operator_gate_rejects_non_owner_actors`` が
    別 human / service / agent / provider / github_app を全 403) で検証済。本 test は budget surface で
    将来 dependency が弱い gate へ swap される regression (= 非 owner / 非 human が budget を engage できる
    退行) を no-DB で捕捉する。"""
    import inspect

    from backend.app.api.budget import (
        clear_global_kill_switch_endpoint,
        engage_global_kill_switch_endpoint,
        get_global_kill_switch_status_endpoint,
    )
    from backend.app.api.dependencies.emergency_stop_operator import (
        require_emergency_stop_operator,
    )

    for endpoint in (
        engage_global_kill_switch_endpoint,
        clear_global_kill_switch_endpoint,
        get_global_kill_switch_status_endpoint,
    ):
        param = inspect.signature(endpoint).parameters["operator_actor_id"]
        # FastAPI の Depends(fn) は ``.dependency == fn`` を持つ。owner gate へ確実に配線されていること。
        assert getattr(param.default, "dependency", None) is require_emergency_stop_operator, (
            f"{endpoint.__name__} の operator_actor_id が require_emergency_stop_operator に "
            "依存していない (owner gate drift = 非 owner が budget kill switch を操作できる退行)"
        )
