"""SP-008: concrete webhook adapter tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.secret_ref import SecretRef
from backend.app.services.repoproxy.webhook_adapters import (
    GITHUB_WEBHOOK_SECRET_CONSUMER,
    GITHUB_WEBHOOK_SECRET_NAME,
    GITHUB_WEBHOOK_SECRET_OPERATION,
    GITHUB_WEBHOOK_SECRET_SCOPE,
    DbWebhookSecretResolver,
    RedisWebhookReplayStore,
)

TENANT_ID = 1
INSTALLATION_ID = 123456
OWNER_ACTOR_ID = UUID("00000000-0000-4000-8000-00000000a001")
CURRENT_REF_ID = UUID("00000000-0000-4000-8000-00000000a101")
PREVIOUS_REF_ID = UUID("00000000-0000-4000-8000-00000000a102")
IGNORED_REF_ID = UUID("00000000-0000-4000-8000-00000000a103")


class _FakeScalars:
    def __init__(self, rows: list[SecretRef]) -> None:
        self._rows = rows

    def all(self) -> list[SecretRef]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[SecretRef]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    def __init__(self, rows: list[SecretRef]) -> None:
        self._rows = rows
        self.tenant_context: int | None = None
        self.query_count = 0

    async def scalar(self, _statement: object) -> str | None:
        if self.tenant_context is None:
            return None
        return str(self.tenant_context)

    async def execute(self, statement: object, parameters: object | None = None) -> _FakeResult:
        if "set_config" in str(statement):
            if not isinstance(parameters, dict):
                raise AssertionError("set_config parameters must be a dict")
            self.tenant_context = int(str(parameters["tenant_id"]))
            return _FakeResult([])
        self.query_count += 1
        return _FakeResult(self._rows)


class _FakeMaterialResolver:
    def __init__(self) -> None:
        self.calls: list[UUID] = []

    async def resolve_secret_material(self, secret_ref: SecretRef) -> bytes | str:
        self.calls.append(secret_ref.id)
        return f"material-for-{secret_ref.version}"


class _FakeRedis:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def set(
        self,
        name: str,
        value: str,
        *,
        ex: int,
        nx: bool,
    ) -> object:
        self.calls.append({"name": name, "value": value, "ex": ex, "nx": nx})
        return self.result


def _secret_ref(
    *,
    ref_id: UUID,
    version: str,
    status: str,
    rotated_from_id: UUID | None = None,
    allowed_consumers: list[str] | None = None,
    allowed_operations: list[str] | None = None,
) -> SecretRef:
    created_at = datetime(2026, 5, 24, 0, 0, tzinfo=UTC)
    return SecretRef(
        id=ref_id,
        tenant_id=TENANT_ID,
        secret_uri=f"secret://sops/{GITHUB_WEBHOOK_SECRET_SCOPE}/{GITHUB_WEBHOOK_SECRET_NAME}#{version}",
        scope=GITHUB_WEBHOOK_SECRET_SCOPE,
        name=GITHUB_WEBHOOK_SECRET_NAME,
        version=version,
        status=status,
        runner_injectable=False,
        allowed_consumers=allowed_consumers or [GITHUB_WEBHOOK_SECRET_CONSUMER],
        allowed_operations=allowed_operations or [GITHUB_WEBHOOK_SECRET_OPERATION],
        owner_actor_id=OWNER_ACTOR_ID,
        rotated_from_id=rotated_from_id,
        metadata_={"rls_ready": True},
        created_at=created_at,
        updated_at=created_at,
    )


@pytest.mark.asyncio
async def test_db_webhook_secret_resolver_returns_active_and_rotated_previous() -> None:
    previous = _secret_ref(ref_id=PREVIOUS_REF_ID, version="v1", status="deprecated")
    ignored = _secret_ref(ref_id=IGNORED_REF_ID, version="v0", status="deprecated")
    current = _secret_ref(
        ref_id=CURRENT_REF_ID,
        version="v2",
        status="active",
        rotated_from_id=PREVIOUS_REF_ID,
    )
    session = _FakeSession([ignored, previous, current])
    material = _FakeMaterialResolver()
    resolver = DbWebhookSecretResolver(
        cast(AsyncSession, session),
        material_resolver=material,
    )

    candidates = await resolver.resolve_webhook_secrets(
        tenant_id=TENANT_ID,
        installation_id=INSTALLATION_ID,
    )

    assert candidates.current is not None
    assert candidates.current.secret_ref_id == CURRENT_REF_ID
    assert candidates.current.secret == b"material-for-v2"
    assert candidates.previous is not None
    assert candidates.previous.secret_ref_id == PREVIOUS_REF_ID
    assert candidates.previous.secret == b"material-for-v1"
    assert material.calls == [CURRENT_REF_ID, PREVIOUS_REF_ID]
    assert session.tenant_context == TENANT_ID
    assert session.query_count == 1


@pytest.mark.asyncio
async def test_db_webhook_secret_resolver_skips_disallowed_secret_refs() -> None:
    current = _secret_ref(
        ref_id=CURRENT_REF_ID,
        version="v2",
        status="active",
        allowed_consumers=["api:other"],
        allowed_operations=[GITHUB_WEBHOOK_SECRET_OPERATION],
    )
    previous = _secret_ref(
        ref_id=PREVIOUS_REF_ID,
        version="v1",
        status="deprecated",
        allowed_consumers=[GITHUB_WEBHOOK_SECRET_CONSUMER],
        allowed_operations=["repo.pr_open"],
    )
    session = _FakeSession([previous, current])
    material = _FakeMaterialResolver()
    resolver = DbWebhookSecretResolver(
        cast(AsyncSession, session),
        material_resolver=material,
    )

    candidates = await resolver.resolve_webhook_secrets(
        tenant_id=TENANT_ID,
        installation_id=INSTALLATION_ID,
    )

    assert candidates.current is None
    assert candidates.previous is None
    assert material.calls == []


@pytest.mark.asyncio
async def test_db_webhook_secret_resolver_does_not_resolve_previous_without_current() -> None:
    previous = _secret_ref(ref_id=PREVIOUS_REF_ID, version="v1", status="deprecated")
    session = _FakeSession([previous])
    material = _FakeMaterialResolver()
    resolver = DbWebhookSecretResolver(
        cast(AsyncSession, session),
        material_resolver=material,
    )

    candidates = await resolver.resolve_webhook_secrets(
        tenant_id=TENANT_ID,
        installation_id=INSTALLATION_ID,
    )

    assert candidates.current is None
    assert candidates.previous is None
    assert material.calls == []


@pytest.mark.asyncio
async def test_redis_webhook_replay_store_claims_with_setnx_ttl() -> None:
    redis = _FakeRedis(True)
    store = RedisWebhookReplayStore(redis)

    claimed = await store.claim_once(key="github-webhook:1:2:abc", ttl_seconds=3600)

    assert claimed is True
    assert redis.calls == [
        {"name": "github-webhook:1:2:abc", "value": "1", "ex": 3600, "nx": True}
    ]


@pytest.mark.asyncio
async def test_redis_webhook_replay_store_rejects_duplicate() -> None:
    redis = _FakeRedis(None)
    store = RedisWebhookReplayStore(redis)

    claimed = await store.claim_once(key="github-webhook:1:2:abc", ttl_seconds=3600)

    assert claimed is False
