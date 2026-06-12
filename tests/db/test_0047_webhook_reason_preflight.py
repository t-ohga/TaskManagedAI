"""migration 0047 (github_webhook_events quarantine_reason CHECK tightening) の preflight test。

旧 CHECK は PostgreSQL の NULL=非違反 semantics で status='quarantined' AND quarantine_reason IS NULL
を許していた。0047 は新 CHECK (IS NOT NULL) を貼る前に、その legacy 状態の row を generic な
'parse_validation_failed' へ remediation する (Codex adversarial review F-high: remediation が無いと
anomaly row が 1 件でも残ると create_check_constraint が失敗して deployment を block する)。

本 test は 0046 まで downgrade し、旧 constraint 下でのみ可能な quarantined+NULL-reason 行を insert、
0047 へ upgrade して (1) row が remediation されること (2) 新 constraint が NULL-reason quarantined を
reject することを固定する。

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

_REV_0046 = "0046_sp027_source_trust"
_REV_0047 = "0047_webhook_reason_not_null"

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
        dev_login_cookie_secret="test-cookie-secret-for-0047-webhook-preflight",
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
            raise AssertionError("0047 webhook preflight test requires PostgreSQL.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    # head から開始 (他 test と同じ前提)。test 本体で 0046 へ落とし 0047 へ戻す。
    await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        # 必ず head に戻す + 本 test が残す webhook row を掃除する (他 test 非汚染)。
        await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
        async with factory.begin() as session:
            await session.execute(text("truncate github_webhook_events restart identity cascade"))
        await engine.dispose()


async def _seed_tenant(session: AsyncSession) -> None:
    await session.execute(
        text(
            "insert into tenants (id, name) values (1, 'webhook-preflight-tenant') "
            "on conflict (id) do nothing"
        )
    )


async def _insert_quarantined(
    session: AsyncSession, *, delivery_id: str, quarantine_reason: str | None
) -> str:
    row_id = str(uuid4())
    await session.execute(
        text(
            "insert into github_webhook_events "
            "(id, tenant_id, repository_id, delivery_id, payload_hash, event_kind, status, "
            " quarantine_reason, received_at) "
            "values (cast(:id as uuid), 1, null, :delivery_id, :payload_hash, 'pull_request', "
            " 'quarantined', :reason, now())"
        ),
        {
            "id": row_id,
            "delivery_id": delivery_id,
            "payload_hash": "sha256:" + "0" * 8,
            "reason": quarantine_reason,
        },
    )
    return row_id


@pytest.mark.asyncio
async def test_0047_preflight_remediates_legacy_null_reason_quarantined_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = _integration_settings()
    # 0046 へ downgrade (0047 の tightening を外し旧 NULL 許容 constraint に戻す)。
    await asyncio.to_thread(_run_alembic, settings.database_url, "downgrade", _REV_0046)

    # 旧 constraint 下でのみ可能な quarantined + NULL-reason の anomaly row を作る。
    async with session_factory.begin() as session:
        await _seed_tenant(session)
        legacy_id = await _insert_quarantined(
            session, delivery_id="legacy-null-reason", quarantine_reason=None
        )

    # 0047 へ upgrade — preflight が legacy row を remediation してから新 constraint を貼る。
    await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", _REV_0047)

    # (1) legacy row は 'parse_validation_failed' へ coerce されている。
    async with session_factory() as session:
        remediated = await session.scalar(
            text("select quarantine_reason from github_webhook_events where id = cast(:id as uuid)"),
            {"id": legacy_id},
        )
    assert remediated == "parse_validation_failed"

    # (2) 新 constraint は NULL-reason quarantined の新規 insert を reject する。
    with pytest.raises(IntegrityError):
        async with session_factory.begin() as session:
            await _insert_quarantined(
                session, delivery_id="post-tighten-null", quarantine_reason=None
            )
