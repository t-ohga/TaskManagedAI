from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.repositories.secret_capability_token import ClaimResult
from backend.app.services.secrets import broker as broker_module
from backend.app.services.secrets.broker import (
    BrokerRedeemDenied,
    BrokerRedeemResult,
    SecretBroker,
)
from backend.app.services.secrets.local_secret_store import LocalSecretStoreError

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000004701")
OTHER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000004702")
RUN_ID = UUID("00000000-0000-4000-8000-000000004703")
SECRET_REF_ID = UUID("00000000-0000-4000-8000-000000004704")
CAPABILITY_ID = UUID("00000000-0000-4000-8000-000000004705")
RAW_TOKEN = "unit-test-capability-token"

INTEGRATION_ACTOR_ID = UUID("00000000-0000-4000-8000-000000004741")
INTEGRATION_RUN_ID = UUID("00000000-0000-4000-8000-000000004742")
INTEGRATION_SECRET_REF_ID = UUID("00000000-0000-4000-8000-000000004743")

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]


class _FakeTokenRepo:
    claim: ClaimResult = ClaimResult.denied("not_found")

    def __init__(self, session: object) -> None:
        self.session = session

    async def atomic_claim(self, **kwargs: object) -> ClaimResult:
        assert kwargs["token_hash"] == hashlib.sha256(RAW_TOKEN.encode("utf-8")).hexdigest()
        assert "expected_request_fingerprint" not in kwargs
        assert isinstance(kwargs["computed_fingerprint"], str)
        return self.claim


class _FakeAuditRepo:
    events: list[dict[str, object]] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def append(self, **kwargs: object) -> object:
        self.events.append(dict(kwargs))
        return object()


class _FakeSession:
    def __init__(self, token: object | None, secret_ref: object | None) -> None:
        self.token = token
        self.secret_ref = secret_ref
        self.updated_statuses: list[str] = []

    async def scalar(self, statement: object) -> object | None:
        statement_text = str(statement)
        if "secret_capability_tokens" in statement_text:
            return self.token
        if "secret_refs" in statement_text:
            return self.secret_ref
        return None

    async def execute(self, statement: object) -> object:
        self.updated_statuses.append(str(statement))
        return object()


@pytest.fixture(autouse=True)
def fake_repositories(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.name == "test_concurrent_redeem_one_time_guarantee":
        return

    _FakeTokenRepo.claim = ClaimResult.denied("not_found")
    _FakeAuditRepo.events = []
    monkeypatch.setattr(broker_module, "SecretCapabilityTokenRepository", _FakeTokenRepo)
    monkeypatch.setattr(broker_module, "AuditEventRepository", _FakeAuditRepo)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-secret-broker-redeem",
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous_database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        command.upgrade(config, "head")
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
            raise AssertionError("SecretBroker redeem tests require PostgreSQL.") from exc
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


def _token() -> SimpleNamespace:
    return SimpleNamespace(
        id=CAPABILITY_ID,
        secret_ref_id=SECRET_REF_ID,
    )


def _secret_ref(
    status: str = "active",
    *,
    name: str = "provider-openai",
    version: str = "v1",
    material_state: str = "present",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=SECRET_REF_ID,
        status=status,
        material_state=material_state,
        scope="project",
        name=name,
        version=version,
        allowed_consumers=[str(ACTOR_ID)],
        allowed_operations=["provider.call"],
    )


def _target() -> dict[str, str]:
    return {
        "provider": "openai",
        "api_or_feature": "responses",
        "model_resolved": "gpt-5.4",
    }


def _scope_constraint(
    *,
    scope: str = "project",
    name: str = "provider-openai",
    version: str = "v1",
) -> dict[str, str]:
    return {"scope": scope, "name": name, "version": version}


@pytest.mark.asyncio
async def test_atomic_claim_zero_rows_returns_broker_redeem_denied() -> None:
    session = _FakeSession(token=_token(), secret_ref=_secret_ref())
    _FakeTokenRepo.claim = ClaimResult.denied("not_found")

    result = await SecretBroker(session=session).redeem_capability_token(  # type: ignore[arg-type]
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        raw_token=RAW_TOKEN,
        requested_operation="provider.call",
        target=_target(),
        payload={"messages": ["hello"]},
        policy_version="policy-v1",
        provider_compliance_matrix_version="pcm-v1",
    )

    assert isinstance(result, BrokerRedeemDenied)
    assert result.reason_code == "not_found"
    assert _FakeAuditRepo.events[0]["event_type"] == "secret_capability_denied"


@pytest.mark.asyncio
async def test_atomic_claim_success_revalidates_secret_and_executes_operation() -> None:
    session = _FakeSession(token=_token(), secret_ref=_secret_ref())
    _FakeTokenRepo.claim = ClaimResult.success(
        capability_id=CAPABILITY_ID,
        secret_ref_id=SECRET_REF_ID,
        allowed_operations=["provider.call"],
        scope_constraint=_scope_constraint(),
    )
    calls: list[UUID] = []

    async def operation(context: broker_module.BrokerOperationContext) -> str:
        calls.append(context.secret_handle.secret_ref_id)
        return "operation-ok"

    result = await SecretBroker(session=session).redeem_capability_token(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        raw_token=RAW_TOKEN,
        requested_operation="provider.call",
        target=_target(),
        payload={"messages": ["hello"]},
        policy_version="policy-v1",
        provider_compliance_matrix_version="pcm-v1",
        operation=operation,
    )

    assert isinstance(result, BrokerRedeemResult)
    assert result.operation_result == "operation-ok"
    assert calls == [SECRET_REF_ID]
    assert _FakeAuditRepo.events[-1]["event_type"] == "secret_capability_redeemed"


@pytest.mark.parametrize(
    ("claim_reason", "expected_reason"),
    [
        ("not_found", "not_found"),
        ("expired", "expired"),
        ("token_used", "token_used"),
        ("actor_mismatch", "actor_mismatch"),
        ("run_mismatch", "run_mismatch"),
        ("fingerprint_mismatch", "fingerprint_mismatch"),
        ("operation_mismatch", "operation_mismatch"),
    ],
)
@pytest.mark.asyncio
async def test_claim_reason_is_preserved(
    claim_reason: str,
    expected_reason: str,
) -> None:
    session = _FakeSession(token=_token(), secret_ref=_secret_ref())
    _FakeTokenRepo.claim = ClaimResult.denied(
        claim_reason,  # type: ignore[arg-type]
        capability_id=CAPABILITY_ID,
        secret_ref_id=SECRET_REF_ID,
    )

    result = await SecretBroker(session=session).redeem_capability_token(  # type: ignore[arg-type]
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        raw_token=RAW_TOKEN,
        requested_operation="provider.call",
        target=_target(),
        payload={"messages": ["hello"]},
        policy_version="policy-v1",
        provider_compliance_matrix_version="pcm-v1",
    )

    assert isinstance(result, BrokerRedeemDenied)
    assert result.reason_code == expected_reason


@pytest.mark.parametrize(
    ("secret_ref", "scope_constraint", "expected_reason"),
    [
        (_secret_ref(name="provider-openai-rotated"), _scope_constraint(), "name_mismatch"),
        (_secret_ref(version="v2"), _scope_constraint(), "version_mismatch"),
        (_secret_ref(), {"scope": "project"}, "name_mismatch"),
    ],
)
@pytest.mark.asyncio
async def test_secret_ref_identity_is_revalidated_after_claim(
    secret_ref: SimpleNamespace,
    scope_constraint: dict[str, object],
    expected_reason: str,
) -> None:
    session = _FakeSession(token=_token(), secret_ref=secret_ref)
    _FakeTokenRepo.claim = ClaimResult.success(
        capability_id=CAPABILITY_ID,
        secret_ref_id=SECRET_REF_ID,
        allowed_operations=["provider.call"],
        scope_constraint=scope_constraint,
    )

    result = await SecretBroker(session=session).redeem_capability_token(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        raw_token=RAW_TOKEN,
        requested_operation="provider.call",
        target=_target(),
        payload={"messages": ["hello"]},
        policy_version="policy-v1",
        provider_compliance_matrix_version="pcm-v1",
    )

    assert isinstance(result, BrokerRedeemDenied)
    assert result.reason_code == expected_reason


@pytest.mark.asyncio
async def test_scope_constraint_must_be_object_after_claim() -> None:
    session = _FakeSession(token=_token(), secret_ref=_secret_ref())
    _FakeTokenRepo.claim = ClaimResult(
        claimed=True,
        reason_code=None,
        capability_id=CAPABILITY_ID,
        secret_ref_id=SECRET_REF_ID,
        allowed_operations=["provider.call"],
        scope_constraint=[],  # type: ignore[arg-type]
    )

    result = await SecretBroker(session=session).redeem_capability_token(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        raw_token=RAW_TOKEN,
        requested_operation="provider.call",
        target=_target(),
        payload={"messages": ["hello"]},
        policy_version="policy-v1",
        provider_compliance_matrix_version="pcm-v1",
    )

    assert isinstance(result, BrokerRedeemDenied)
    assert result.reason_code == "scope_constraint_invalid"


@pytest.mark.asyncio
async def test_secret_ref_revoked_after_claim_denies_without_operation() -> None:
    session = _FakeSession(token=_token(), secret_ref=_secret_ref(status="revoked"))
    _FakeTokenRepo.claim = ClaimResult.success(
        capability_id=CAPABILITY_ID,
        secret_ref_id=SECRET_REF_ID,
        allowed_operations=["provider.call"],
        scope_constraint=_scope_constraint(),
    )
    called = False

    async def operation(context: broker_module.BrokerOperationContext) -> str:
        nonlocal called
        called = True
        return "should-not-run"

    result = await SecretBroker(session=session).redeem_capability_token(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        raw_token=RAW_TOKEN,
        requested_operation="provider.call",
        target=_target(),
        payload={"messages": ["hello"]},
        policy_version="policy-v1",
        provider_compliance_matrix_version="pcm-v1",
        operation=operation,
    )

    assert isinstance(result, BrokerRedeemDenied)
    assert result.reason_code == "secret_ref_revoked"
    assert called is False


@pytest.mark.asyncio
async def test_resolver_custody_failure_after_claim_denies_and_revokes() -> None:
    """Codex R14-F2: atomic claim 後の resolver custody 失敗を fail-closed deny にする。

    LocalSecretStore は marker 不在 / backend drift / permission / decrypt 失敗で raise するように
    なった。これが claim 済 token を消費したまま例外伝播すると、secret_capability_denied audit と token
    revoke を bypass し 500 + token_used 誤分類になる。broker は例外を捕捉し denied + revoke + audit する。
    """
    session = _FakeSession(token=_token(), secret_ref=_secret_ref())  # active + present
    _FakeTokenRepo.claim = ClaimResult.success(
        capability_id=CAPABILITY_ID,
        secret_ref_id=SECRET_REF_ID,
        allowed_operations=["provider.call"],
        scope_constraint=_scope_constraint(),
    )
    op_called = False

    async def operation(context: broker_module.BrokerOperationContext) -> str:
        nonlocal op_called
        op_called = True
        return "should-not-run"

    async def failing_resolver(secret_ref: object) -> bytes:
        raise LocalSecretStoreError("backend marker missing (simulated custody failure)")

    result = await SecretBroker(
        session=session,  # type: ignore[arg-type]
        secret_resolver=failing_resolver,
    ).redeem_capability_token(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        raw_token=RAW_TOKEN,
        requested_operation="provider.call",
        target=_target(),
        payload={"messages": ["hello"]},
        policy_version="policy-v1",
        provider_compliance_matrix_version="pcm-v1",
        operation=operation,
    )

    assert isinstance(result, BrokerRedeemDenied)
    assert result.reason_code == "material_not_present"
    assert op_called is False  # custody 失敗で broker-mediated operation は実行されない
    # token は burn されず denied audit が残る (redeemed audit は出ない)。
    assert any(e["event_type"] == "secret_capability_denied" for e in _FakeAuditRepo.events)
    assert all(e["event_type"] != "secret_capability_redeemed" for e in _FakeAuditRepo.events)


@pytest.mark.asyncio
async def test_operation_custody_failure_after_claim_denies_and_revokes() -> None:
    """Codex R15-F1: operation 内の再 resolve (例: RepoProxy transport が installation token を再 resolve)
    が custody 失敗で raise した場合も、pre-resolve と同じく denied + token revoke + denied audit にする。

    operation を try 外に置くと、custody 失敗が claim 済 token を消費したまま例外伝播し 500 + token_used
    誤分類になる。非 custody な operation 失敗 (provider/GitHub error) のみ従来どおり伝播させる。
    """
    session = _FakeSession(token=_token(), secret_ref=_secret_ref())  # active + present
    _FakeTokenRepo.claim = ClaimResult.success(
        capability_id=CAPABILITY_ID,
        secret_ref_id=SECRET_REF_ID,
        allowed_operations=["provider.call"],
        scope_constraint=_scope_constraint(),
    )

    async def operation(context: broker_module.BrokerOperationContext) -> str:
        # operation 内で material 再 resolve が custody 失敗するのを模擬。
        raise LocalSecretStoreError("backend drift during operation (simulated)")

    result = await SecretBroker(session=session).redeem_capability_token(  # type: ignore[arg-type]
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        raw_token=RAW_TOKEN,
        requested_operation="provider.call",
        target=_target(),
        payload={"messages": ["hello"]},
        policy_version="policy-v1",
        provider_compliance_matrix_version="pcm-v1",
        operation=operation,
    )

    assert isinstance(result, BrokerRedeemDenied)
    assert result.reason_code == "material_not_present"
    assert any(e["event_type"] == "secret_capability_denied" for e in _FakeAuditRepo.events)
    assert all(e["event_type"] != "secret_capability_redeemed" for e in _FakeAuditRepo.events)


@pytest.mark.asyncio
async def test_non_custody_operation_failure_propagates() -> None:
    """Codex R15-F1 の対: 非 custody な operation 失敗 (provider/GitHub error) は従来どおり伝播する
    (custody 失敗のみ denied 化、通常の operation 失敗は token 消費済で例外伝播)。"""
    session = _FakeSession(token=_token(), secret_ref=_secret_ref())
    _FakeTokenRepo.claim = ClaimResult.success(
        capability_id=CAPABILITY_ID,
        secret_ref_id=SECRET_REF_ID,
        allowed_operations=["provider.call"],
        scope_constraint=_scope_constraint(),
    )

    async def operation(context: broker_module.BrokerOperationContext) -> str:
        raise RuntimeError("provider 5xx (simulated non-custody failure)")

    with pytest.raises(RuntimeError):
        await SecretBroker(session=session).redeem_capability_token(  # type: ignore[arg-type]
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            raw_token=RAW_TOKEN,
            requested_operation="provider.call",
            target=_target(),
            payload={"messages": ["hello"]},
            policy_version="policy-v1",
            provider_compliance_matrix_version="pcm-v1",
            operation=operation,
        )


async def _reset_integration_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              audit_events,
              secret_capability_tokens,
              secret_refs,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _setup_integration_secret_ref(session: AsyncSession) -> None:
    await _reset_integration_tables(session)
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            """
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (
              :actor_id, 1, 'human', 'human:secret-broker-redeem',
              'SecretBroker Redeem Actor', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"actor_id": INTEGRATION_ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into secret_refs (
              id,
              tenant_id,
              secret_uri,
              scope,
              name,
              version,
              status,
              runner_injectable,
              allowed_consumers,
              allowed_operations,
              owner_actor_id,
              metadata,
              material_state
            )
            values (
              :secret_ref_id,
              1,
              'secret://sops/project/provider-openai#v1',
              'project',
              'provider-openai',
              'v1',
              'active',
              false,
              cast(:allowed_consumers as jsonb),
              cast(:allowed_operations as jsonb),
              :actor_id,
              '{"rls_ready": true}'::jsonb,
              'present'
            )
            """
        ),
        {
            "secret_ref_id": INTEGRATION_SECRET_REF_ID,
            "actor_id": INTEGRATION_ACTOR_ID,
            "allowed_consumers": json.dumps([str(INTEGRATION_ACTOR_ID)]),
            "allowed_operations": json.dumps(["provider.call"]),
        },
    )


@pytest.mark.asyncio
async def test_concurrent_redeem_one_time_guarantee(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_integration_secret_ref(session)
        broker = SecretBroker(session=session)
        issue_result = await broker.issue_capability_token(
            tenant_id=TENANT_ID,
            actor_id=INTEGRATION_ACTOR_ID,
            run_id=INTEGRATION_RUN_ID,
            secret_ref_id=INTEGRATION_SECRET_REF_ID,
            requested_operation="provider.call",
            target=_target(),
            payload_hash="0" * 64,
            policy_version="policy-v1",
            provider_compliance_matrix_version="pcm-v1",
        )
        await session.commit()

    async def _redeem_attempt() -> tuple[str, BrokerRedeemDenied | None]:
        async with session_factory() as session:
            broker = SecretBroker(session=session)
            result = await broker.redeem_capability_token(
                tenant_id=TENANT_ID,
                actor_id=INTEGRATION_ACTOR_ID,
                run_id=INTEGRATION_RUN_ID,
                raw_token=issue_result.raw_token,
                requested_operation="provider.call",
                target=_target(),
                payload_hash="0" * 64,
                policy_version="policy-v1",
                provider_compliance_matrix_version="pcm-v1",
            )
            if isinstance(result, BrokerRedeemDenied):
                await session.rollback()
                return ("denied", result)
            await session.commit()
            return ("success", None)

    results = await asyncio.gather(_redeem_attempt(), _redeem_attempt())
    successes = [result for result in results if result[0] == "success"]
    denieds = [result for result in results if result[0] == "denied"]

    assert len(successes) == 1
    assert len(denieds) == 1
    assert denieds[0][1] is not None
    assert denieds[0][1].reason_code in {"not_found", "token_used"}


def test_audit_payload_names_do_not_include_raw_secret_or_raw_token() -> None:
    payload = {
        "reason_code": "fingerprint_mismatch",
        "capability_id": str(CAPABILITY_ID),
        "secret_ref_id": str(SECRET_REF_ID),
        "requested_operation": "provider.call",
        "expected_request_fingerprint_hash": "0" * 64,
    }
    assert "raw_token" not in payload
    assert "raw_secret" not in payload
    assert "capability_token" not in payload

