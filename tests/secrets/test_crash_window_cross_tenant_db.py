"""SP-PHASE0 S4 #4: create/rotate crash-window + cross-tenant material identity (DB-gated)。

ADR-00058 finding-2 / ADR-00059:
- **create crash-window**: register は pending+material_state='writing' row を commit してから store 書込→
  present 昇格する。途中 crash すると pending+writing orphan row が残る (material は未書込 or 部分書込)。
  ``gc_orphans`` が grace 経過後に writing-orphan を revoked+purging へ tombstone し、revoke-orphan purge で
  store material を idempotent に削除して収束する。
- **cross-tenant material identity**: material key は ``tenant_id + secret_ref_id`` 束縛。tenant A の
  material を tenant B (別 tenant_id、同 secret_ref_id を仮に渡しても) で resolve できない。LocalSecretStore
  の service 名が tenant_id を含むため、cross-tenant 誤解決が構造的に起きないことを固定する。

batch-1 教訓 (a): ``gc_orphans`` の writing-orphan tombstone は ``updated_at < cutoff`` を見るため、grace を
過ぎた orphan を作るには **explicit に古い updated_at で raw-INSERT** する (UPDATE は BEFORE UPDATE trigger
``secret_refs_set_updated_at`` が now() で上書きするため backdate 不可)。

``TASKMANAGEDAI_RUN_DB_TESTS=1`` + test PostgreSQL でのみ実行。
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.services.secrets.local_secret_store import (
    LocalSecretMaterialNotFound,
    LocalSecretStore,
)
from backend.app.services.secrets.material_reconciliation import (
    MaterialReconciliationService,
)
from backend.app.services.secrets.secret_registration import SecretRegistrationService
from tests.secrets._db_harness import (
    fetch_secret_ref_row,
    insert_actor,
    insert_tenant,
    reset_secret_tables,
)

pytestmark = pytest.mark.asyncio

TENANT_A = 1
TENANT_B = 2
ACTOR_A = UUID("00000000-0000-4000-8000-0000000c0001")
ACTOR_B = UUID("00000000-0000-4000-8000-0000000c0002")
RAW_A = b"tenant-a-material-RAW"
RAW_B = b"tenant-b-material-RAW"


def _store(tmp_path: Path) -> LocalSecretStore:
    return LocalSecretStore(base_dir=tmp_path, use_keyring=False)


async def _seed_two_tenants(session: AsyncSession) -> None:
    await reset_secret_tables(session)
    await insert_tenant(session, TENANT_A, "tenant-a")
    await insert_tenant(session, TENANT_B, "tenant-b")
    await insert_actor(session, tenant_id=TENANT_A, actor_id=ACTOR_A, stable_actor_id="human:a")
    await insert_actor(session, tenant_id=TENANT_B, actor_id=ACTOR_B, stable_actor_id="human:b")
    await session.commit()


async def _raw_insert_writing_orphan(
    session: AsyncSession,
    *,
    tenant_id: int,
    owner_actor_id: UUID,
    age_seconds: int,
    name: str = "provider-openai",
) -> UUID:
    """pending+writing local secret_ref を **古い updated_at** で raw-INSERT (create crash 残骸の擬似)。"""
    secret_ref_id = uuid4()
    await session.execute(
        text(
            """
            insert into secret_refs (
              id, tenant_id, secret_uri, scope, name, version, status,
              runner_injectable, allowed_consumers, allowed_operations, owner_actor_id, metadata,
              material_state, created_at, updated_at
            )
            values (
              :id, :tenant_id, :uri, 'project', :name, 'v1', 'pending', false,
              cast(:consumers as jsonb), cast(:operations as jsonb), :owner,
              '{"rls_ready": true}'::jsonb, 'writing',
              now() - make_interval(secs => :age), now() - make_interval(secs => :age)
            )
            """
        ),
        {
            "id": secret_ref_id,
            "tenant_id": tenant_id,
            "uri": f"secret://local/project/{name}#v1",
            "name": name,
            "consumers": "[]",
            "operations": "[]",
            "owner": owner_actor_id,
            "age": age_seconds,
        },
    )
    await session.commit()
    return secret_ref_id


# ---- create crash-window: gc_orphans converges writing-orphan ----


async def test_gc_orphans_converges_create_writing_orphan(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    async with session_factory() as session:
        await _seed_two_tenants(session)
        # store に partial material が残った擬似 (store 書込後 / present 昇格前 crash)。
        # store.store は marker を pin する。secret_ref_id は orphan row と一致させる。
        orphan_id = await _raw_insert_writing_orphan(
            session, tenant_id=TENANT_A, owner_actor_id=ACTOR_A, age_seconds=3600
        )
        store.store(TENANT_A, orphan_id, RAW_A)
        assert store.exists(TENANT_A, orphan_id)

        recon = MaterialReconciliationService(session=session, store=store)
        report = await recon.gc_orphans(tenant_id=TENANT_A, writing_grace_seconds=300)

        # writing-orphan は tombstone (rolled_back) → revoke-orphan purge で material 削除 (purged)。
        assert str(orphan_id) in report.rolled_back, report
        assert str(orphan_id) in report.purged, report

        row = await fetch_secret_ref_row(session, TENANT_A, orphan_id)
        assert row is not None
        assert row["status"] == "revoked"
        assert row["material_state"] == "purged"
        assert row["material_purged_at"] is not None
        # store material は削除済 (idempotent purge 収束)。
        assert not store.exists(TENANT_A, orphan_id)


async def test_gc_orphans_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """2 回目の gc_orphans は no-op (収束済を再破壊しない)。"""
    store = _store(tmp_path)
    async with session_factory() as session:
        await _seed_two_tenants(session)
        orphan_id = await _raw_insert_writing_orphan(
            session, tenant_id=TENANT_A, owner_actor_id=ACTOR_A, age_seconds=3600
        )
        store.store(TENANT_A, orphan_id, RAW_A)
        recon = MaterialReconciliationService(session=session, store=store)
        await recon.gc_orphans(tenant_id=TENANT_A, writing_grace_seconds=300)

        second = await recon.gc_orphans(tenant_id=TENANT_A, writing_grace_seconds=300)
        # 既に purged → tombstone も purge も新規には起きない。
        assert str(orphan_id) not in second.rolled_back
        assert str(orphan_id) not in second.purged

        row = await fetch_secret_ref_row(session, TENANT_A, orphan_id)
        assert row is not None
        assert row["status"] == "revoked"
        assert row["material_state"] == "purged"


async def test_gc_orphans_respects_grace_for_in_flight_writing(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """grace 内 (fresh) の pending+writing は in-flight register として tombstone しない。"""
    store = _store(tmp_path)
    async with session_factory() as session:
        await _seed_two_tenants(session)
        # age=1s (grace 300s 未満) = in-flight register 中の擬似。
        fresh_id = await _raw_insert_writing_orphan(
            session, tenant_id=TENANT_A, owner_actor_id=ACTOR_A, age_seconds=1
        )
        recon = MaterialReconciliationService(session=session, store=store)
        report = await recon.gc_orphans(tenant_id=TENANT_A, writing_grace_seconds=300)
        assert str(fresh_id) not in report.rolled_back
        row = await fetch_secret_ref_row(session, TENANT_A, fresh_id)
        assert row is not None
        assert row["status"] == "pending"
        assert row["material_state"] == "writing"


# ---- cross-tenant material identity (key = tenant_id + secret_ref_id) ----


async def test_material_key_binds_tenant_id_no_cross_tenant_resolve(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    async with session_factory() as session:
        await _seed_two_tenants(session)
        svc = SecretRegistrationService(session=session, store=store)
        ref_a = await svc.register(
            tenant_id=TENANT_A,
            scope="project",
            name="provider-openai",
            version="v1",
            owner_actor_id=ACTOR_A,
            raw_material=RAW_A,
            allowed_consumers=[str(ACTOR_A)],
            allowed_operations=["provider.call"],
        )
        ref_b = await svc.register(
            tenant_id=TENANT_B,
            scope="project",
            name="provider-openai",
            version="v1",
            owner_actor_id=ACTOR_B,
            raw_material=RAW_B,
            allowed_consumers=[str(ACTOR_B)],
            allowed_operations=["provider.call"],
        )

        # 各 tenant は自分の material を resolve できる。
        assert store.resolve(TENANT_A, ref_a.id) == RAW_A
        assert store.resolve(TENANT_B, ref_b.id) == RAW_B

        # tenant B 名義で tenant A の secret_ref_id を resolve しようとしても not found
        # (key = tenant_id + secret_ref_id 束縛、cross-tenant 同名 secret が衝突・誤解決しない)。
        with pytest.raises(LocalSecretMaterialNotFound):
            store.resolve(TENANT_B, ref_a.id)
        with pytest.raises(LocalSecretMaterialNotFound):
            store.resolve(TENANT_A, ref_b.id)

        # tenant A の material は B の値と混同しない。
        assert store.resolve(TENANT_A, ref_a.id) != RAW_B
