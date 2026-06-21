"""taskhub secret-create / secret-rotate / secret-revoke CLI helpers (SP-PHASE0 S3、ADR-00058/00059)。

``SecretRegistrationService`` (crash-safe local material lifecycle) を CLI から invokable にする
**operational path**。raw material は CLI 引数 (argv) では**一切受け取らず** (argv は ``ps`` 等で
world-visible)、呼び出し側 (taskhub_admin) が ``getpass.getpass()`` (interactive) または stdin から
読み取った ``bytes`` を本 helper へ渡す。本 helper は DB session / store を bootstrap し service を
呼ぶだけで、raw material を log / print / persist しない (DB 保存は service 経由の ciphertext のみ)。

raw secret 値は report dict に一切含めない (secret_uri / status / secret_ref_id / 件数のみ)。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
    )

    from backend.app.db.models.secret_ref import SecretRef, SecretRefScope


def _build_session_factory(
    database_url: str | None,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """async engine + sessionmaker を作る (taskhub_secret_gc と同 pattern)。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    if database_url is None:
        from backend.app.config import get_settings

        database_url = get_settings().database_url

    engine = create_async_engine(database_url, pool_pre_ping=True)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    return engine, factory


def _ref_report(ref: SecretRef) -> dict[str, Any]:
    """raw secret を含まない非機密 metadata report (secret_uri / status / lifecycle のみ)。"""
    return {
        "secret_ref_id": str(ref.id),
        "secret_uri": ref.secret_uri,
        "scope": ref.scope,
        "name": ref.name,
        "version": ref.version,
        "status": ref.status,
        "material_state": ref.material_state,
    }


async def _resolve_owner_actor_id(session: AsyncSession, tenant_id: int) -> UUID:
    """owner_actor_id を DB の default human actor から解決する (caller-supplied actor を避ける)。"""
    from backend.app.repositories.actor import ActorRepository

    actor = await ActorRepository(session).get_human_default(tenant_id)
    return actor.id


def create_secret(
    *,
    tenant_id: int,
    scope: SecretRefScope,
    name: str,
    version: str,
    raw_material: bytes,
    allowed_consumers: list[str],
    allowed_operations: list[str],
    metadata: dict[str, Any] | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    """新 local secret を crash-safe に登録し active 昇格する (SecretRegistrationService.register)。

    ``raw_material`` は caller (taskhub_admin) が getpass/stdin から読み取った ``bytes``。本 helper は
    それを service へ渡すだけで、log/print/persist しない。
    """
    from backend.app.services.secrets.local_secret_store import LocalSecretStore
    from backend.app.services.secrets.secret_registration import (
        SecretRegistrationService,
    )

    async def _run() -> dict[str, Any]:
        engine, factory = _build_session_factory(database_url)
        try:
            async with factory() as session:
                owner_actor_id = await _resolve_owner_actor_id(session, tenant_id)
                service = SecretRegistrationService(session, LocalSecretStore())
                ref = await service.register(
                    tenant_id=tenant_id,
                    scope=scope,
                    name=name,
                    version=version,
                    owner_actor_id=owner_actor_id,
                    raw_material=raw_material,
                    allowed_consumers=allowed_consumers,
                    allowed_operations=allowed_operations,
                    backend="local",
                    metadata=metadata,
                )
                return _ref_report(ref)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def rotate_secret(
    *,
    tenant_id: int,
    old_secret_ref_id: UUID,
    new_version: str,
    raw_material: bytes,
    allowed_consumers: list[str],
    allowed_operations: list[str],
    metadata: dict[str, Any] | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    """既存 local secret を rotate し新 version を pending+present で配置する (active 化しない)。

    promote (新 active + 旧 deprecated) は ``secret.verify`` / smoke 通過後の別 step (本 CLI 外)。
    """
    from backend.app.services.secrets.local_secret_store import LocalSecretStore
    from backend.app.services.secrets.secret_registration import (
        SecretRegistrationService,
    )

    async def _run() -> dict[str, Any]:
        engine, factory = _build_session_factory(database_url)
        try:
            async with factory() as session:
                owner_actor_id = await _resolve_owner_actor_id(session, tenant_id)
                service = SecretRegistrationService(session, LocalSecretStore())
                ref = await service.rotate(
                    tenant_id=tenant_id,
                    old_secret_ref_id=old_secret_ref_id,
                    new_version=new_version,
                    owner_actor_id=owner_actor_id,
                    raw_material=raw_material,
                    allowed_consumers=allowed_consumers,
                    allowed_operations=allowed_operations,
                    metadata=metadata,
                )
                return _ref_report(ref)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def revoke_secret(
    *,
    tenant_id: int,
    secret_ref_id: UUID,
    database_url: str | None = None,
) -> dict[str, Any]:
    """secret_ref を revoke する (rule §5: active/deprecated/pending → revoked)。

    material 削除は revoked 確定後の best-effort purge + ``secret-gc-orphans`` reconciliation
    (本 helper は ``SecretRegistrationService.revoke`` を呼ぶだけ、rotation.py.revoke は流用しない)。
    """
    from backend.app.services.secrets.local_secret_store import LocalSecretStore
    from backend.app.services.secrets.secret_registration import (
        SecretRegistrationService,
    )

    async def _run() -> dict[str, Any]:
        engine, factory = _build_session_factory(database_url)
        try:
            async with factory() as session:
                service = SecretRegistrationService(session, LocalSecretStore())
                ref = await service.revoke(
                    tenant_id=tenant_id,
                    secret_ref_id=secret_ref_id,
                )
                return _ref_report(ref)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


__all__ = ["create_secret", "revoke_secret", "rotate_secret"]
