"""SP-PHASE0 S4 #5: false-present 防止 e2e (DB-gated)。

DB default ``material_state='writing'`` (store 未完了 row が false-present にならない安全側)。token issue /
redeem の secret_ref 検証で ``material_state='present'`` を必須化する (boundary §7/§9)。

本 test:
1. **issue gate**: material 未書込 (material_state='writing') の local secret_ref を raw-INSERT (store には
   material 無し) → ``issue_capability_token`` が ``material_not_present`` で deny。
2. **redeem gate**: present な secret を register→issue した後、material_state を raw-UPDATE で writing /
   purging / purged に戻す → redeem が ``material_not_present`` で deny (false-present な未完了 material から
   secret を resolve させない)。

``TASKMANAGEDAI_RUN_DB_TESTS=1`` + test PostgreSQL でのみ実行。
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.services.secrets.broker import (
    BrokerIssueDenied,
    BrokerRedeemDenied,
    SecretBroker,
)
from backend.app.services.secrets.local_secret_store import LocalSecretStore
from backend.app.services.secrets.resolver_dispatch import CompositeSecretResolver
from backend.app.services.secrets.secret_registration import SecretRegistrationService
from tests.secrets._db_harness import (
    insert_actor,
    insert_tenant,
    reset_secret_tables,
)

pytestmark = pytest.mark.asyncio

ACTOR_ID = UUID("00000000-0000-4000-8000-0000000b0001")
RUN_ID = UUID("00000000-0000-4000-8000-0000000b0003")
RAW_MATERIAL = b"present-material-raw"
TARGET = {"provider": "openai", "api_or_feature": "responses", "model_resolved": "gpt-5.4"}
PAYLOAD = {"messages": ["hi"]}


def _store(tmp_path: Path) -> LocalSecretStore:
    return LocalSecretStore(base_dir=tmp_path, use_keyring=False)


def _broker(session: AsyncSession, store: LocalSecretStore) -> SecretBroker:
    return SecretBroker(session=session, secret_resolver=CompositeSecretResolver(local_store=store))


async def _seed_tenant_actor(session: AsyncSession) -> None:
    await reset_secret_tables(session)
    await insert_tenant(session, 1, "tenant-one")
    await insert_actor(session, tenant_id=1, actor_id=ACTOR_ID, stable_actor_id="human:tenant-one")
    await session.commit()


async def _raw_insert_writing_local_secret(session: AsyncSession) -> UUID:
    """material_state を **明示せず** local secret_ref を raw-INSERT (default 'writing'、store 書込なし)。"""
    secret_ref_id = uuid4()
    await session.execute(
        text(
            """
            insert into secret_refs (
              id, tenant_id, secret_uri, scope, name, version, status,
              runner_injectable, allowed_consumers, allowed_operations, owner_actor_id, metadata
            )
            values (
              :id, 1, 'secret://local/project/provider-openai#v1', 'project', 'provider-openai',
              'v1', 'active', false,
              cast(:consumers as jsonb), cast(:operations as jsonb), :owner, '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "id": secret_ref_id,
            "consumers": f'["{ACTOR_ID}"]',
            "operations": '["provider.call"]',
            "owner": ACTOR_ID,
        },
    )
    await session.commit()
    return secret_ref_id


async def _material_state_of(session: AsyncSession, secret_ref_id: UUID) -> str:
    value = await session.scalar(
        text("select material_state from secret_refs where tenant_id = 1 and id = :id"),
        {"id": secret_ref_id},
    )
    return str(value)


# ---- issue gate ----


async def test_issue_denies_when_material_state_defaulted_to_writing(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    async with session_factory() as session:
        await _seed_tenant_actor(session)
        secret_ref_id = await _raw_insert_writing_local_secret(session)

        # default は writing (material 未書込 = false-present の元) であることを固定。
        assert await _material_state_of(session, secret_ref_id) == "writing"

        broker = _broker(session, store)
        with pytest.raises(BrokerIssueDenied) as exc:
            await broker.issue_capability_token(
                tenant_id=1,
                actor_id=ACTOR_ID,
                run_id=RUN_ID,
                secret_ref_id=secret_ref_id,
                requested_operation="provider.call",
                target=TARGET,
                payload=PAYLOAD,
                policy_version="policy-v1",
                provider_compliance_matrix_version="pcm-v1",
            )
        assert exc.value.reason_code == "material_not_present"


# ---- redeem gate (material reverted after issue) ----


@pytest.mark.parametrize("reverted_state", ["writing", "purging", "purged"])
async def test_redeem_denies_when_material_state_not_present(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    reverted_state: str,
) -> None:
    store = _store(tmp_path)
    async with session_factory() as session:
        await _seed_tenant_actor(session)
        service = SecretRegistrationService(session=session, store=store)
        ref = await service.register(
            tenant_id=1,
            scope="project",
            name="provider-openai",
            version="v1",
            owner_actor_id=ACTOR_ID,
            raw_material=RAW_MATERIAL,
            allowed_consumers=[str(ACTOR_ID)],
            allowed_operations=["provider.call"],
        )
        assert ref.material_state == "present"
        broker = _broker(session, store)
        issue = await broker.issue_capability_token(
            tenant_id=1,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            secret_ref_id=ref.id,
            requested_operation="provider.call",
            target=TARGET,
            payload=PAYLOAD,
            policy_version="policy-v1",
            provider_compliance_matrix_version="pcm-v1",
        )
        await session.commit()

        # material_state を present 以外へ raw-UPDATE (BEFORE UPDATE trigger は updated_at のみ書換える
        # ため material_state はそのまま反映される)。DB CHECK 制約に合わせて status も整合させる:
        #   - writing: status は active のまま可 (writing は active local の create 途中状態)。
        #   - purging/purged: ck_material_purge_requires_revoked が status='revoked' を必須化。
        #     purged は ck_material_purged_at_state が material_purged_at non-NULL を必須化。
        if reverted_state == "purged":
            await session.execute(
                text(
                    "update secret_refs set status='revoked', material_state='purged', "
                    "material_purged_at=now() where tenant_id=1 and id=:id"
                ),
                {"id": ref.id},
            )
        elif reverted_state == "purging":
            await session.execute(
                text(
                    "update secret_refs set status='revoked', material_state='purging' "
                    "where tenant_id=1 and id=:id"
                ),
                {"id": ref.id},
            )
        else:
            await session.execute(
                text(
                    "update secret_refs set material_state=:state where tenant_id=1 and id=:id"
                ),
                {"id": ref.id, "state": reverted_state},
            )
        await session.commit()
        assert await _material_state_of(session, ref.id) == reverted_state
        raw_token = issue.raw_token

    # redeem は fresh session (clean identity map = stale cache を避ける、worker process 分離の擬似)。
    async with session_factory() as redeem_session:
        redeem_broker = _broker(redeem_session, store)
        result = await redeem_broker.redeem_capability_token(
            tenant_id=1,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            raw_token=raw_token,
            requested_operation="provider.call",
            target=TARGET,
            payload=PAYLOAD,
            policy_version="policy-v1",
            provider_compliance_matrix_version="pcm-v1",
        )
        await redeem_session.commit()

        assert isinstance(result, BrokerRedeemDenied)
        # writing (status=active) は material_not_present。purging/purged は DB CHECK 上 status=revoked が
        # 必須のため secret_ref_revoked が先に出る (どちらも false-present な material を resolve させない
        # 正しい deny)。いずれも raw secret resolve には到達しない。
        if reverted_state == "writing":
            assert result.reason_code == "material_not_present"
        else:
            assert result.reason_code in {"secret_ref_revoked", "material_not_present"}
