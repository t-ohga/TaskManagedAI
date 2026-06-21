"""SP-PHASE0 S4 #6: revoke crash-window + migration 0050 downgrade 3 条件 preflight (DB-gated)。

ADR-00059:
- **revoke crash-window**: revoke は status='revoked' を commit してから store delete する別 step。途中 crash
  すると ``material_purged_at IS NULL`` の revoked row が残る (material は store に残存)。``gc_orphans`` が
  ``LocalSecretStore.delete`` を idempotent に試み、成功時のみ ``material_state='purged'`` +
  ``material_purged_at=now()`` を set して収束する (「revoked=削除済」は material_purged_at non-NULL で初めて真)。
- **0050 downgrade 3 条件 preflight** (full rollback 0050→0049 の skew 防止):
  (a) ``status='revoked' AND material_purged_at IS NULL AND secret_uri LIKE 'secret://local/%'`` 0 件
  (b) ``material_state IN ('writing','purging')`` 0 件
  (c) ``secret_uri LIKE 'secret://local/%'`` 0 件
  いずれか残存で downgrade が ``RuntimeError`` で fail-fast。3 条件すべて満たせば downgrade 成功。

本 test は専用 session_factory (teardown で必ず head へ戻す) を使い、他 test 非汚染。
``TASKMANAGEDAI_RUN_DB_TESTS=1`` + test PostgreSQL でのみ実行。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import get_settings
from backend.app.db.session import create_engine
from backend.app.services.secrets.local_secret_store import LocalSecretStore
from backend.app.services.secrets.material_reconciliation import (
    MaterialReconciliationService,
)
from backend.app.services.secrets.secret_registration import SecretRegistrationService
from tests.secrets._db_harness import (
    assert_database_available,
    fetch_secret_ref_row,
    insert_actor,
    insert_tenant,
    integration_settings,
    reset_secret_tables,
)

pytestmark = pytest.mark.asyncio

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REV_0049 = "0049_secret_uri_local_backend"
_REV_0050 = "0050_secret_material_lifecycle"

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-0000000d0001")
RAW_MATERIAL = b"revoke-crash-material-RAW"


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


@pytest_asyncio.fixture
async def factory_at_head() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = integration_settings()
    await assert_database_available(settings)
    await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        # downgrade を走らせる test があるため必ず head へ戻す + secret tables を掃除 (他 test 非汚染)。
        await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", "head")
        async with factory() as session:
            await reset_secret_tables(session)
            await session.commit()
        await engine.dispose()


def _store(tmp_path: Path) -> LocalSecretStore:
    return LocalSecretStore(base_dir=tmp_path, use_keyring=False)


async def _register_active_local(
    session: AsyncSession, store: LocalSecretStore, *, name: str = "provider-openai"
) -> UUID:
    svc = SecretRegistrationService(session=session, store=store)
    ref = await svc.register(
        tenant_id=TENANT_ID,
        scope="project",
        name=name,
        version="v1",
        owner_actor_id=ACTOR_ID,
        raw_material=RAW_MATERIAL,
        allowed_consumers=[str(ACTOR_ID)],
        allowed_operations=["provider.call"],
    )
    return ref.id


async def _seed(session: AsyncSession) -> None:
    await reset_secret_tables(session)
    await insert_tenant(session, TENANT_ID, "tenant-one")
    await insert_actor(session, tenant_id=TENANT_ID, actor_id=ACTOR_ID, stable_actor_id="human:one")
    await session.commit()


def _simulate_revoke_crash_before_purge(store: LocalSecretStore) -> LocalSecretStore:
    """store.delete だけ失敗させ best-effort purge 失敗 (DB revoked 後 / material purge 前 crash) を擬似する。"""

    def _raise_delete(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated crash before material purge")

    store.delete = _raise_delete  # type: ignore[method-assign,assignment]
    return store


# ---- revoke crash-window: gc_orphans purges leftover material ----


async def test_revoke_crash_then_gc_orphans_converges(
    factory_at_head: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with factory_at_head() as session:
        await _seed(session)
        store = _store(tmp_path)
        secret_ref_id = await _register_active_local(session, store)
        assert store.exists(TENANT_ID, secret_ref_id)

        # revoke 中に store.delete が失敗 (DB revoked commit 後 / material purge 前 crash の擬似)。
        crash_store = _store(tmp_path)
        _simulate_revoke_crash_before_purge(crash_store)
        crash_svc = SecretRegistrationService(session=session, store=crash_store)
        ref = await crash_svc.revoke(tenant_id=TENANT_ID, secret_ref_id=secret_ref_id)
        # status は revoked だが purge 失敗で material_purged_at は NULL (未 purge = まだ削除済でない)。
        assert ref.status == "revoked"
        row = await fetch_secret_ref_row(session, TENANT_ID, secret_ref_id)
        assert row is not None
        assert row["status"] == "revoked"
        assert row["material_purged_at"] is None
        assert row["material_state"] == "purging"
        # material は store に残存している (crash で削除されなかった)。
        assert store.exists(TENANT_ID, secret_ref_id)

        # gc_orphans が material を idempotent に削除して収束する (real store)。
        recon = MaterialReconciliationService(session=session, store=store)
        report = await recon.gc_orphans(tenant_id=TENANT_ID, writing_grace_seconds=300)
        assert str(secret_ref_id) in report.purged, report

        row2 = await fetch_secret_ref_row(session, TENANT_ID, secret_ref_id)
        assert row2 is not None
        assert row2["material_state"] == "purged"
        assert row2["material_purged_at"] is not None
        assert not store.exists(TENANT_ID, secret_ref_id)


# ---- downgrade 3 条件 preflight ----


async def test_downgrade_blocked_when_local_revoked_unpurged(
    factory_at_head: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """condition (a): local revoked + material_purged_at IS NULL が残ると downgrade fail-fast。"""
    settings = integration_settings()
    async with factory_at_head() as session:
        await _seed(session)
        store = _store(tmp_path)
        secret_ref_id = await _register_active_local(session, store)
        crash_store = _store(tmp_path)
        _simulate_revoke_crash_before_purge(crash_store)
        crash_svc = SecretRegistrationService(session=session, store=crash_store)
        await crash_svc.revoke(tenant_id=TENANT_ID, secret_ref_id=secret_ref_id)

    # 0050→0049 downgrade は revoked-unpurged local row があるため block。
    with pytest.raises(RuntimeError, match="0050 downgrade blocked"):
        await asyncio.to_thread(_run_alembic, settings.database_url, "downgrade", _REV_0049)


async def test_downgrade_blocked_when_local_rows_present(
    factory_at_head: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """condition (c): present な local row が残ると downgrade fail-fast (material 残存)。"""
    settings = integration_settings()
    async with factory_at_head() as session:
        await _seed(session)
        store = _store(tmp_path)
        await _register_active_local(session, store)

    with pytest.raises(RuntimeError, match="0050 downgrade blocked"):
        await asyncio.to_thread(_run_alembic, settings.database_url, "downgrade", _REV_0049)


async def test_downgrade_succeeds_after_gc_converges_and_local_removed(
    factory_at_head: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """3 条件すべて満たすと downgrade 成功 → 再 upgrade で復旧。

    local row は (a) gc で revoked+purged に収束させても (c) `secret://local/%` 行が残るため downgrade は
    なお block する (material lifecycle は local material が完全に無くなるまで rollback させない設計)。
    本 test は no-local-rows 状態 (sops 行のみ / 行なし) で downgrade が通ることを固定する。
    """
    settings = integration_settings()
    async with factory_at_head() as session:
        await _seed(session)
        # local row を作らず、3 条件すべて 0 件 (clean) の状態にする。
        # sops 行 (present) は downgrade を block しない (condition は local scope)。
        await session.execute(
            text(
                """
                insert into secret_refs (
                  id, tenant_id, secret_uri, scope, name, version, status,
                  runner_injectable, allowed_consumers, allowed_operations, owner_actor_id,
                  metadata, material_state
                )
                values (
                  gen_random_uuid(), :tenant_id, 'secret://sops/project/legacy-key#v1',
                  'project', 'legacy-key', 'v1', 'active', false,
                  '["actor:x"]'::jsonb, '["provider.call"]'::jsonb, :owner,
                  '{"rls_ready": true}'::jsonb, 'present'
                )
                """
            ),
            {"tenant_id": TENANT_ID, "owner": ACTOR_ID},
        )
        await session.commit()
        # 3 条件確認: local revoked-unpurged=0, writing/purging=0, local rows=0。
        local_count = await session.scalar(
            text("select count(*) from secret_refs where secret_uri like 'secret://local/%'")
        )
        assert local_count == 0

    # downgrade 成功 (sops present 行は block しない)。
    await asyncio.to_thread(_run_alembic, settings.database_url, "downgrade", _REV_0049)

    # 0049 では lifecycle 3 列が無いことを確認。
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            cols = await conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name='secret_refs' and column_name in "
                    "('material_state','material_purged_at','purge_attempts')"
                )
            )
            assert cols.scalars().all() == []
    finally:
        await engine.dispose()

    # 再 upgrade で復旧 (teardown も head へ戻すが明示的に確認)。
    await asyncio.to_thread(_run_alembic, settings.database_url, "upgrade", _REV_0050)
    engine2 = create_engine(settings.database_url)
    try:
        async with engine2.connect() as conn:
            cols2 = await conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name='secret_refs' and column_name='material_state'"
                )
            )
            assert cols2.scalars().all() == ["material_state"]
    finally:
        await engine2.dispose()
