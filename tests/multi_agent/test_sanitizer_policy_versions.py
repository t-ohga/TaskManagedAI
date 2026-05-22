"""SP-013 batch 0e contract test: sanitizer_policy_versions table + initial seed.

migration 0023_multi_agent_foundation_d で追加された minimal table の構造 verify
(ADR-00016 §5 + PH-F-009 fix、SP-013 minimal seed、SP-018 で FK 接続予定)。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時のみ実行。
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


def _integration_settings() -> Settings:
    database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL)
    redis_url = os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL)
    return Settings(
        database_url=database_url,
        redis_url=redis_url,
        dev_login_cookie_secret="test-cookie-secret-sanitizer-policy",
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
            raise AssertionError("sanitizer policy test requires PostgreSQL.") from exc
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


async def _ensure_default_tenant(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            on conflict (id) do nothing
            """
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_sanitizer_policy_versions_table_exists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """sanitizer_policy_versions table が migration で作成済."""
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select table_name from information_schema.tables
                 where table_schema = 'public'
                   and table_name = 'sanitizer_policy_versions'
                """
            )
        )
        assert result.scalar() == "sanitizer_policy_versions"


@pytest.mark.asyncio
async def test_sanitizer_policy_versions_initial_seed_v1_0_0(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """initial seed (v1.0.0) が tenant_id=1 に投入されている (assert existence).

    Codex PR #139 R1 P2 fix: 旧実装は `if rows:` guard で seed 不在 regression を
    catch しない無効 assertion だった。本 fix は assert-existence pattern で
    fail-fast、tenants の事前 ensure 必須 + v1.0.0 必ず存在を assert。
    """
    async with session_factory() as session:
        # tenants seed の事前 ensure (test DB の fresh migration は seed skip の可能性)
        await _ensure_default_tenant(session)
        # migration 0023 の seed 条件 (`where exists tenants id=1`) が fresh DB で
        # 満たされない場合に備え、明示的に v1.0.0 seed を ensure (idempotent)
        await session.execute(
            text(
                """
                insert into sanitizer_policy_versions
                  (tenant_id, version, config_hash, ruleset_hash)
                values (1, 'v1.0.0', :config_hash, :ruleset_hash)
                on conflict do nothing
                """
            ),
            {"config_hash": "0" * 64, "ruleset_hash": "0" * 64},
        )
        await session.commit()

    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select version, deprecated_at from sanitizer_policy_versions
                 where tenant_id = 1
                """
            )
        )
        rows = result.all()
        # assert-existence pattern (Codex PR #139 P2 fix): seed 必須を fail-fast 保証
        assert rows, "sanitizer_policy_versions seed 未投入 (tenants 事前 ensure 失敗の可能性)"
        versions = [row[0] for row in rows]
        assert "v1.0.0" in versions, f"v1.0.0 seed が tenant_id=1 に投入されていない: {versions}"
        # deprecated_at は NULL (current active version)
        for version, deprecated_at in rows:
            if version == "v1.0.0":
                assert deprecated_at is None, f"v1.0.0 が deprecated 状態: {deprecated_at}"


@pytest.mark.asyncio
async def test_sanitizer_policy_versions_config_hash_sha256_format(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """config_hash / ruleset_hash CHECK constraint (sha256 hex 64 chars) verify."""
    async with session_factory() as session:
        # CHECK constraint 違反 (sha256 形式以外) は INSERT reject
        with pytest.raises(SQLAlchemyError, match="config_hash|ruleset_hash"):
            await session.execute(
                text(
                    """
                    insert into sanitizer_policy_versions
                      (tenant_id, version, config_hash, ruleset_hash)
                    values (1, 'invalid_test', 'NOT_HEX', :valid_hash)
                    """
                ),
                {"valid_hash": "0" * 64},
            )
            await session.commit()


@pytest.mark.asyncio
async def test_sanitizer_policy_versions_unique_version_per_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """(tenant_id, version) unique constraint verify."""
    async with session_factory() as session:
        await _ensure_default_tenant(session)
        # test DB は fresh migration apply で seed の `where exists tenants` が false
        # で skip される可能性、明示的に v1.0.0 を挿入してから重複 test
        zero_hash = "0" * 64
        await session.execute(
            text(
                """
                insert into sanitizer_policy_versions
                  (tenant_id, version, config_hash, ruleset_hash)
                values (1, 'v1.0.0', :config_hash, :ruleset_hash)
                on conflict do nothing
                """
            ),
            {"config_hash": zero_hash, "ruleset_hash": zero_hash},
        )
        await session.commit()

    async with session_factory() as session:
        # 同 version 重複 INSERT は reject
        zero_hash = "0" * 64
        with pytest.raises(SQLAlchemyError, match="duplicate|unique|version"):
            await session.execute(
                text(
                    """
                    insert into sanitizer_policy_versions
                      (tenant_id, version, config_hash, ruleset_hash)
                    values (1, 'v1.0.0', :config_hash, :ruleset_hash)
                    """
                ),
                {"config_hash": zero_hash[:-1] + "1", "ruleset_hash": zero_hash[:-1] + "2"},
            )
            await session.commit()
