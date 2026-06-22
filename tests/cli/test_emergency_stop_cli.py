"""SP-PHASE1 B6: emergency-stop operator CLI (ADR-00048 §C/§D) DB-gated test。

検証 (must-ship):
- ``status`` が未engage / engage 後の latch 状態を返す。
- ``engage`` が latch を設定し active run を block する (service と同じ semantics)。
- ``clear`` が generation CAS で latch を解除し run を復元する。
- stale generation の ``clear`` は exit code 2 (precondition fail)。
- human-only: configured owner が非 human / 別 stable id だと resolve 失敗で exit 2 (kill されない)。
- 出力に raw secret / token / pid を含まない。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container。
"""

from __future__ import annotations

import asyncio
import json
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

from backend.app.cli import emergency_stop as cli
from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ONE = 1
ACTOR_OWNER_1 = UUID("00000000-0000-4000-8000-0000000d6001")
ACTOR_AGENT_1 = UUID("00000000-0000-4000-8000-0000000d6002")
WORKSPACE_1 = UUID("00000000-0000-4000-8000-0000000d6010")
PROJECT_1 = UUID("00000000-0000-4000-8000-0000000d6020")

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
        dev_login_cookie_secret="test-cookie-secret-for-emergency-stop-cli",
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
        raise AssertionError("emergency-stop CLI tests require PostgreSQL.") from exc
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)
    # CLI は get_settings() を読むため、test 用 settings を返すよう差し替える (cache を test scope で固定)。
    get_settings.cache_clear()
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    # wake publish は Redis 不在でも no-op (best-effort)。CLI engage が Redis 障害で落ちないことを確認。
    monkeypatch.setattr(
        cli, "publish_emergency_stop_wake", _noop_wake_publish, raising=True
    )
    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _noop_wake_publish(**_kwargs: object) -> bool:
    return False


async def _reset(session: AsyncSession) -> None:
    await session.execute(
        text(
            "truncate superintendent_emergency_stops, agent_run_events, agent_runs, "
            "audit_events, projects, workspaces, actors, tenants restart identity cascade"
        )
    )
    await session.commit()


async def _seed(session: AsyncSession, *, owner_actor_type: str = "human") -> None:
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
            values
              (:o1, 1, :otype, 'human:default', 'Owner1', '{"rls_ready": true}'::jsonb),
              (:a1, 1, 'agent', 'agent:r1', 'Agent1', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"o1": ACTOR_OWNER_1, "a1": ACTOR_AGENT_1, "otype": owner_actor_type},
    )
    await session.execute(
        text(
            "insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata) "
            "values (:w1, 1, 'ws1', 'ws1', :o1, '{\"rls_ready\": true}'::jsonb)"
        ),
        {"w1": WORKSPACE_1, "o1": ACTOR_OWNER_1},
    )
    await session.execute(
        text(
            "insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata) "
            "values (:p1, 1, :w1, 'p1', 'p1', 'active', '{\"rls_ready\": true}'::jsonb)"
        ),
        {"p1": PROJECT_1, "w1": WORKSPACE_1},
    )
    await session.commit()


async def _make_run(session: AsyncSession, *, status: str) -> UUID:
    rid = uuid4()
    await session.execute(
        text(
            "insert into agent_runs "
            "(id, tenant_id, project_id, status, blocked_reason, run_mode) "
            "values (:r, 1, :p, :s, null, 'production')"
        ),
        {"r": rid, "p": PROJECT_1, "s": status},
    )
    await session.commit()
    return rid


async def _invoke(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict[str, object]]:
    """CLI を **async test の event loop 内で** 駆動する。

    ``cli.main`` は ``asyncio.run(_run(...))`` で wrap するため running loop 内では呼べない。本 helper は
    実コードの parser + ``_run`` (CLI 本体ロジック) を直接 await して同じ経路を検証する。
    """
    args = cli._build_parser().parse_args(argv)
    code = await cli._run(args)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out) if out else {}
    return code, payload


@pytest.mark.asyncio
async def test_status_engage_clear_roundtrip(
    session_factory: async_sessionmaker[AsyncSession],
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)
        run_id = await _make_run(session, status="running")

    # status: 未engage
    code, payload = await _invoke(["status"], capsys)
    assert code == 0
    assert payload["engaged"] is False
    assert payload["generation"] is None

    # engage: latch 設定 + running run を block
    code, payload = await _invoke(["engage", "--reason", "runaway agent"], capsys)
    assert code == 0
    assert payload["engaged"] is True
    assert payload["already_engaged"] is False
    assert payload["blocked_run_count"] == 1
    generation = payload["generation"]
    assert isinstance(generation, int)

    # status: engage 後
    code, payload = await _invoke(["status"], capsys)
    assert code == 0
    assert payload["engaged"] is True
    assert payload["generation"] == generation

    # run が blocked + pre_stop_status=running に遷移したことを DB で確認
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "select status, blocked_reason, pre_stop_status "
                    "from agent_runs where id = :r"
                ),
                {"r": run_id},
            )
        ).one()
        assert row.status == "blocked"
        assert row.blocked_reason == "runtime_blocked"
        assert row.pre_stop_status == "running"

    # clear: generation CAS で解除 + run 復元
    code, payload = await _invoke(["clear", "--generation", str(generation)], capsys)
    assert code == 0
    assert payload["cleared"] is True
    assert payload["resumed_run_count"] == 1

    async with session_factory() as session:
        row = (
            await session.execute(
                text("select status, blocked_reason, pre_stop_status from agent_runs where id = :r"),
                {"r": run_id},
            )
        ).one()
        assert row.status == "running"
        assert row.blocked_reason is None
        assert row.pre_stop_status is None


@pytest.mark.asyncio
async def test_clear_stale_generation_fails(
    session_factory: async_sessionmaker[AsyncSession],
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    code, payload = await _invoke(["engage"], capsys)
    assert code == 0
    generation = payload["generation"]
    assert isinstance(generation, int)

    # stale generation → exit 2、latch は残る
    code, payload = await _invoke(["clear", "--generation", str(generation + 99)], capsys)
    assert code == 2
    assert payload["error"] == "emergency_stop_precondition_failed"

    code, payload = await _invoke(["status"], capsys)
    assert payload["engaged"] is True


@pytest.mark.asyncio
async def test_clear_when_not_engaged_fails(
    session_factory: async_sessionmaker[AsyncSession],
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    code, payload = await _invoke(["clear", "--generation", "1"], capsys)
    assert code == 2
    assert payload["error"] == "emergency_stop_precondition_failed"


@pytest.mark.asyncio
async def test_reason_with_secret_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with session_factory() as session:
        await _reset(session)
        await _seed(session)

    # raw provider token を reason に混入 → service の broad scanner で reject、exit 2、latch 不在
    code, payload = await _invoke(
        ["engage", "--reason", "key sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"],
        capsys,
    )
    assert code == 2
    assert payload["error"] == "emergency_stop_precondition_failed"
    # 出力に raw token を漏らさない
    assert "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789" not in json.dumps(payload)

    code, payload = await _invoke(["status"], capsys)
    assert payload["engaged"] is False


@pytest.mark.asyncio
async def test_non_human_owner_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # configured owner stable id が service actor の場合 (human-only 違反) → resolve 失敗、exit 2
    async with session_factory() as session:
        await _reset(session)
        await _seed(session, owner_actor_type="service")

    code, payload = await _invoke(["engage"], capsys)
    assert code == 2
    assert payload["error"] == "emergency_stop_precondition_failed"
    assert "human-only" in payload["message"]

    code, payload = await _invoke(["status"], capsys)
    assert code == 2  # status も human-only 境界を要求する
