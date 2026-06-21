"""SP-PHASE0 S4 #2: secret register → issue → redeem の e2e (DB-gated)。

LocalSecretStore (file mode) で raw material を登録し、``SecretRegistrationService.register`` で
``material_state='present'`` + ``active`` に昇格、``SecretBroker.issue_capability_token`` で TTL token を
発行、``redeem_capability_token`` で **broker 内部のみ** material を resolve する。CompositeSecretResolver
を broker に配線し、operation callback には raw secret ではなく ``SecretHandle`` のみが渡ることを固定する。

NEGATIVE: actor mismatch / run mismatch / fingerprint mismatch / operation mismatch を redeem し、すべて
0-row atomic claim で deny されること、かつ audit payload に raw secret / raw token が含まれないことを
``assert_no_raw_secret`` で固定する (boundary §8 / §11)。

``TASKMANAGEDAI_RUN_DB_TESTS=1`` + test PostgreSQL でのみ実行。
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.secrets.broker import (
    BrokerOperationContext,
    BrokerRedeemDenied,
    BrokerRedeemResult,
    SecretBroker,
    SecretHandle,
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

ACTOR_ID = UUID("00000000-0000-4000-8000-0000000a0001")
OTHER_ACTOR_ID = UUID("00000000-0000-4000-8000-0000000a0002")
RUN_ID = UUID("00000000-0000-4000-8000-0000000a0003")
OTHER_RUN_ID = UUID("00000000-0000-4000-8000-0000000a0004")

RAW_MATERIAL = b"super-secret-provider-key-RAW-do-not-leak"
TARGET = {
    "provider": "openai",
    "api_or_feature": "responses",
    "model_resolved": "gpt-5.4",
}
PAYLOAD = {"messages": ["hello"]}


def _store(tmp_path: Path) -> LocalSecretStore:
    # file mode を強制 (keyring 不在 / 無効環境でも決定的、CI parity)。
    return LocalSecretStore(base_dir=tmp_path, use_keyring=False)


def _broker(session: AsyncSession, store: LocalSecretStore) -> SecretBroker:
    resolver = CompositeSecretResolver(local_store=store)
    return SecretBroker(session=session, secret_resolver=resolver)


async def _seed_local_secret(
    session: AsyncSession, store: LocalSecretStore
) -> UUID:
    await reset_secret_tables(session)
    await insert_tenant(session, 1, "tenant-one")
    await insert_actor(session, tenant_id=1, actor_id=ACTOR_ID, stable_actor_id="human:tenant-one")
    await insert_actor(
        session, tenant_id=1, actor_id=OTHER_ACTOR_ID, stable_actor_id="human:other"
    )
    await session.commit()

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
        metadata=None,
    )
    assert ref.status == "active"
    assert ref.material_state == "present"
    return ref.id


async def _issue(broker: SecretBroker, secret_ref_id: UUID) -> str:
    issue = await broker.issue_capability_token(
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
    return issue.raw_token


async def _audit_payloads(session: AsyncSession) -> list[dict[str, object]]:
    result = await session.execute(
        text("select event_type, event_payload from audit_events where tenant_id = 1")
    )
    return [
        {"event_type": row["event_type"], **dict(row["event_payload"])}
        for row in result.mappings().all()
    ]


async def _assert_no_raw_secret_in_audit(session: AsyncSession) -> None:
    payloads = await _audit_payloads(session)
    assert payloads, "expected at least one secret audit event"
    raw_str = RAW_MATERIAL.decode()
    for payload in payloads:
        # 構造化 prohibited-key / pattern scan (boundary §11)。
        assert_no_raw_secret(payload)
        # raw material 値が plaintext で混入しない。
        assert raw_str not in str(payload), f"raw material leaked into audit: {payload}"


# ---- positive: e2e resolve via broker internal only ----


async def test_e2e_register_issue_redeem_resolves_internally(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    async with session_factory() as session:
        secret_ref_id = await _seed_local_secret(session, store)
        broker = _broker(session, store)
        raw_token = await _issue(broker, secret_ref_id)
        await session.commit()

        seen_handles: list[object] = []

        async def operation(context: BrokerOperationContext) -> str:
            # caller (operation callback) は SecretHandle のみを受け取り、raw secret は受け取らない。
            seen_handles.append(context.secret_handle)
            return "provider-response-ok"

        result = await broker.redeem_capability_token(
            tenant_id=1,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            raw_token=raw_token,
            requested_operation="provider.call",
            target=TARGET,
            payload=PAYLOAD,
            policy_version="policy-v1",
            provider_compliance_matrix_version="pcm-v1",
            operation=operation,
        )
        await session.commit()

        assert isinstance(result, BrokerRedeemResult)
        assert result.operation_result == "provider-response-ok"
        # operation は SecretHandle のみ受け取る (raw bytes / token は渡らない)。
        assert len(seen_handles) == 1
        handle = seen_handles[0]
        assert isinstance(handle, SecretHandle)
        assert handle.secret_ref_id == secret_ref_id
        assert RAW_MATERIAL.decode() not in repr(handle)

        # broker は store から raw material を内部 resolve できる (操作主体は broker)。
        assert store.resolve(1, secret_ref_id) == RAW_MATERIAL

        await _assert_no_raw_secret_in_audit(session)


async def test_e2e_redeem_is_one_time(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """同一 token の 2 回目 redeem は token_used / not_found で deny (one-time atomic claim)。"""
    store = _store(tmp_path)
    async with session_factory() as session:
        secret_ref_id = await _seed_local_secret(session, store)
        broker = _broker(session, store)
        raw_token = await _issue(broker, secret_ref_id)
        await session.commit()

        first = await broker.redeem_capability_token(
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
        await session.commit()
        assert isinstance(first, BrokerRedeemResult)

        second = await broker.redeem_capability_token(
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
        await session.commit()
        assert isinstance(second, BrokerRedeemDenied)
        assert second.reason_code in {"token_used", "not_found"}
        await _assert_no_raw_secret_in_audit(session)


# ---- negative: mismatch denies (0-row atomic claim) ----


@pytest.mark.parametrize(
    ("mutate", "expected_reasons"),
    [
        # token は直前に issue+commit 済 (row 存在) のため _classify_denied_claim は precise reason を返す。
        # anti-gaming のため not_found fallback を許容せず exact reason_code を固定する (Workflow S4 review LOW
        # adopt、boundary §8: mismatch ごとに distinct deny reason、diagnostic-collapse 回帰も捕捉する)。
        ("actor", {"actor_mismatch"}),
        ("run", {"run_mismatch"}),
        ("fingerprint", {"fingerprint_mismatch"}),
        # operation を変えると requested_operation が OperationContext に含まれ fingerprint が先に不一致になり
        # fingerprint_mismatch で 0-row deny する (operation_mismatch leg を shadow)。operation_mismatch 単独 leg は
        # fingerprint を保ったまま検証する pre-existing tests/runtime/test_secret_broker_negative.py が担保済。
        # 本 case は「operation substitution → fingerprint 不一致 → deny」を固定 (not_found は許容しない)。
        ("operation", {"fingerprint_mismatch", "operation_mismatch"}),
    ],
)
async def test_e2e_redeem_mismatch_denies(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    mutate: str,
    expected_reasons: set[str],
) -> None:
    store = _store(tmp_path)
    async with session_factory() as session:
        secret_ref_id = await _seed_local_secret(session, store)
        # operation mismatch case は allowed_operations に repo.push を入れない (provider.call 専用)。
        broker = _broker(session, store)
        raw_token = await _issue(broker, secret_ref_id)
        await session.commit()

        kwargs: dict[str, object] = {
            "tenant_id": 1,
            "actor_id": ACTOR_ID,
            "run_id": RUN_ID,
            "raw_token": raw_token,
            "requested_operation": "provider.call",
            "target": TARGET,
            "payload": PAYLOAD,
            "policy_version": "policy-v1",
            "provider_compliance_matrix_version": "pcm-v1",
        }
        if mutate == "actor":
            kwargs["actor_id"] = OTHER_ACTOR_ID
        elif mutate == "run":
            kwargs["run_id"] = OTHER_RUN_ID
        elif mutate == "fingerprint":
            # target を変えると broker 再計算 fingerprint が issue 時と不一致 → claim 0 row。
            kwargs["target"] = {**TARGET, "model_resolved": "gpt-tampered"}
        elif mutate == "operation":
            kwargs["requested_operation"] = "secret.verify"
            kwargs["target"] = {"secret_ref_id": str(secret_ref_id), "version": "v1"}

        result = await broker.redeem_capability_token(**kwargs)  # type: ignore[arg-type]
        await session.commit()

        assert isinstance(result, BrokerRedeemDenied), f"{mutate} should deny"
        assert result.reason_code in expected_reasons, (
            f"{mutate}: got {result.reason_code}, expected one of {expected_reasons}"
        )

        # raw secret / token は store に残るが material はまだ purge されない (deny は consume しない設計に
        # 依存しないため status は確認しない)。audit に raw が出ないことのみ固定。
        await _assert_no_raw_secret_in_audit(session)
