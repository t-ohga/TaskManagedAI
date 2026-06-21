"""Concrete adapters for the GitHub webhook verifier boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import assert_tenant_context, get_tenant_context, set_tenant_context
from backend.app.db.models.secret_ref import SecretRef, SecretRefScope
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.services.repoproxy.webhook_service import (
    WebhookSecretCandidate,
    WebhookSecretCandidates,
)

GITHUB_WEBHOOK_SECRET_SCOPE: SecretRefScope = "p0"  # noqa: S105 - secret ref scope only.
GITHUB_WEBHOOK_SECRET_NAME = "github_webhook_hmac"  # noqa: S105 - secret ref name only.
GITHUB_WEBHOOK_SECRET_CONSUMER = "api:repo_proxy"  # noqa: S105 - consumer id only.
GITHUB_WEBHOOK_SECRET_OPERATION = "secret.verify"  # noqa: S105 - operation id only.


class SecretMaterialResolver(Protocol):
    """Resolve raw secret bytes for a SecretRef outside database storage."""

    async def resolve_secret_material(
        self, secret_ref: SecretRef, *, allow_pending_verify: bool = False
    ) -> bytes | str:
        # allow_pending_verify=True は broker 経由の rotation verify 専用 (Codex R18-F1)。direct/webhook
        # 利用は default False で pending を拒否し fail-closed を維持する。
        ...


class RedisSetClient(Protocol):
    """Minimal redis.asyncio.Redis SET contract used by the replay store."""

    async def set(
        self,
        name: str,
        value: str,
        *,
        ex: int,
        nx: bool,
    ) -> object: ...


class DbWebhookSecretResolver:
    """Resolve active/deprecated GitHub webhook HMAC candidates from SecretRef rows.

    SecretRef rows intentionally contain only metadata. Secret bytes are provided
    by an injected material resolver so DB storage never grows raw secret columns.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        material_resolver: SecretMaterialResolver,
        scope: SecretRefScope = GITHUB_WEBHOOK_SECRET_SCOPE,
        name: str = GITHUB_WEBHOOK_SECRET_NAME,
        required_consumer: str = GITHUB_WEBHOOK_SECRET_CONSUMER,
        required_operation: str = GITHUB_WEBHOOK_SECRET_OPERATION,
    ) -> None:
        self._session = session
        self._material_resolver = material_resolver
        self._scope = scope
        self._name = name
        self._required_consumer = required_consumer
        self._required_operation = required_operation

    async def resolve_webhook_secrets(
        self,
        *,
        tenant_id: int,
        installation_id: int,
    ) -> WebhookSecretCandidates:
        _require_positive_int(tenant_id, field_name="tenant_id")
        _require_positive_int(installation_id, field_name="installation_id")
        await self._ensure_tenant_context(tenant_id)

        result = await self._session.execute(
            select(SecretRef)
            .where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.scope == self._scope,
                SecretRef.name == self._name,
                SecretRef.status.in_(("active", "deprecated")),
            )
            .order_by(SecretRef.created_at, SecretRef.id)
        )
        rows = list(result.scalars().all())
        current_ref = _select_current(rows, self._required_consumer, self._required_operation)
        previous_ref = (
            _select_previous(
                rows,
                current_ref=current_ref,
                required_consumer=self._required_consumer,
                required_operation=self._required_operation,
            )
            if current_ref is not None
            else None
        )
        return WebhookSecretCandidates(
            current=await self._to_candidate(current_ref),
            previous=await self._to_candidate(previous_ref),
        )

    async def _to_candidate(self, secret_ref: SecretRef | None) -> WebhookSecretCandidate | None:
        if secret_ref is None:
            return None
        material = await self._material_resolver.resolve_secret_material(secret_ref)
        secret = _coerce_secret_bytes(material)
        return WebhookSecretCandidate(
            secret_ref_id=secret_ref.id,
            version=secret_ref.version,
            status=secret_ref.status,
            secret=secret,
        )

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        current_tenant_id = await get_tenant_context(self._session)
        if current_tenant_id is None:
            await set_tenant_context(self._session, tenant_id)
        await assert_tenant_context(self._session, tenant_id)


class RedisWebhookReplayStore:
    """Atomic webhook replay guard backed by Redis ``SET key 1 EX ttl NX``."""

    def __init__(self, redis: RedisSetClient) -> None:
        self._redis = redis

    @classmethod
    def from_url(cls, redis_url: str) -> RedisWebhookReplayStore:
        from redis.asyncio import Redis

        return cls(cast(RedisSetClient, Redis.from_url(redis_url, decode_responses=True)))

    async def claim_once(self, *, key: str, ttl_seconds: int) -> bool:
        if not key:
            raise ValueError("key must be non-empty.")
        _require_positive_int(ttl_seconds, field_name="ttl_seconds")
        result = await self._redis.set(key, "1", ex=ttl_seconds, nx=True)
        return result is True or result in {"OK", b"OK", 1}


class DbWebhookAuditSink:
    """Append webhook verifier audit payloads to ``audit_events``."""

    def __init__(self, session: AsyncSession) -> None:
        self._repository = AuditEventRepository(session)

    async def append(
        self,
        *,
        tenant_id: int,
        event_type: str,
        payload: dict[str, object],
    ) -> object:
        return await self._repository.append(
            tenant_id=tenant_id,
            event_type=event_type,
            payload=payload,
        )


def _select_current(
    rows: list[SecretRef],
    required_consumer: str,
    required_operation: str,
) -> SecretRef | None:
    for row in rows:
        if row.status == "active" and _matches_allowlist(
            row,
            required_consumer=required_consumer,
            required_operation=required_operation,
        ):
            return row
    return None


def _select_previous(
    rows: list[SecretRef],
    *,
    current_ref: SecretRef | None,
    required_consumer: str,
    required_operation: str,
) -> SecretRef | None:
    deprecated = [
        row
        for row in rows
        if row.status == "deprecated"
        and _matches_allowlist(
            row,
            required_consumer=required_consumer,
            required_operation=required_operation,
        )
    ]
    if not deprecated:
        return None
    if current_ref is not None and current_ref.rotated_from_id is not None:
        for row in deprecated:
            if row.id == current_ref.rotated_from_id:
                return row
    return deprecated[-1]


def _matches_allowlist(
    secret_ref: SecretRef,
    *,
    required_consumer: str,
    required_operation: str,
) -> bool:
    return (
        required_consumer in secret_ref.allowed_consumers
        and required_operation in secret_ref.allowed_operations
    )


def _coerce_secret_bytes(material: bytes | str) -> bytes:
    if isinstance(material, bytes):
        return material
    if isinstance(material, str):
        return material.encode("utf-8")
    raise TypeError("secret material resolver must return bytes or str.")


def _require_positive_int(value: int, *, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer.")


WebhookSecretMaterialCallable = Callable[[SecretRef], bytes | str | Awaitable[bytes | str]]


__all__ = [
    "GITHUB_WEBHOOK_SECRET_CONSUMER",
    "GITHUB_WEBHOOK_SECRET_NAME",
    "GITHUB_WEBHOOK_SECRET_OPERATION",
    "GITHUB_WEBHOOK_SECRET_SCOPE",
    "DbWebhookAuditSink",
    "DbWebhookSecretResolver",
    "RedisSetClient",
    "RedisWebhookReplayStore",
    "SecretMaterialResolver",
    "WebhookSecretMaterialCallable",
]
