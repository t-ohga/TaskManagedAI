"""MaterialReconciliationService: broker-owned (local) material の durable orphan reconciliation。

``secret gc-orphans`` の本体 (idempotent、定期 or 手動)。2 種の orphan を収束させる:

1. **revoke orphan** (``status='revoked' AND material_purged_at IS NULL`` の local row): revoke は DB
   commit と store delete の境界跨ぎのため、DB revoked 後に crash すると material が store に残存する。
   本 reconciliation が ``LocalSecretStore.delete()`` を idempotent に試み、成功時のみ
   ``material_state='purged'`` + ``material_purged_at=now()`` を set する。「revoked=削除済」表示は
   material_purged_at non-NULL で初めて真 (ADR-00059)。

2. **create/rotate orphan** (``material_state='writing'`` の local row): register/rotate は pending+
   writing row を commit してから store 書込→present 昇格する。途中 crash すると pending+writing row が
   残る。grace period 経過後 (in-flight register と race しない) に store の partial material を削除し
   pending+writing row を rollback (破棄) する (ADR-00058 finding-2)。

material 操作は ``rotation.py`` の外 (status-only invariant を壊さない)。本 service は broker-owned
**local** backend のみ対象 (sops material は外部管理)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.secret_ref import SecretRef
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.services.secrets.local_secret_store import LocalSecretStore

logger = logging.getLogger(__name__)

_LOCAL_URI_PREFIX = "secret://local/"
_DEFAULT_WRITING_GRACE_SECONDS = 300


@dataclass
class ReconciliationReport:
    purged: list[str] = field(default_factory=list)
    purge_failed: list[str] = field(default_factory=list)
    rolled_back: list[str] = field(default_factory=list)

    @property
    def total_actions(self) -> int:
        return len(self.purged) + len(self.purge_failed) + len(self.rolled_back)


class MaterialReconciliationService:
    """local material の revoke-orphan purge + create/rotate-orphan rollback (idempotent)。"""

    def __init__(self, session: AsyncSession, store: LocalSecretStore) -> None:
        self.session = session
        self.store = store

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
            return
        await assert_tenant_context(self.session, tenant_id)

    async def _audit(self, *, tenant_id: int, event_type: str, secret_ref_id: UUID, reason: str) -> None:
        repo = AuditEventRepository(self.session)
        await repo.append(
            tenant_id=tenant_id,
            event_type=event_type,
            payload={"secret_ref_id": str(secret_ref_id), "reason_code": reason},
        )

    async def gc_orphans(
        self,
        *,
        tenant_id: int,
        writing_grace_seconds: int = _DEFAULT_WRITING_GRACE_SECONDS,
    ) -> ReconciliationReport:
        await self._ensure_tenant_context(tenant_id)
        report = ReconciliationReport()
        # (1) writing-orphan を revoked+purging へ tombstone する (DB owner を残す)。row を delete すると
        #     grace 超過後に resume した late writer が owner なし orphan material を生む (Codex F2)。
        # (2) 続けて revoke-orphan (tombstone 済 + 通常 revoked) の material を idempotent に purge する。
        await self._tombstone_writing_orphans(tenant_id, writing_grace_seconds, report)
        await self._purge_revoke_orphans(tenant_id, report)
        return report

    async def _purge_revoke_orphans(self, tenant_id: int, report: ReconciliationReport) -> None:
        # local revoked 行を **全件** (purged 含む) 走査し store.delete を idempotent backstop として
        # 実行する (Codex R2-F2): tombstone+purged 確定後に late writer が store.store で material を
        # 再作成し cleanup 前に crash した場合でも、次回 gc が再削除し永久 orphan を防ぐ。
        rows = await self.session.execute(
            select(SecretRef.id, SecretRef.material_purged_at).where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.status == "revoked",
                SecretRef.secret_uri.like(f"{_LOCAL_URI_PREFIX}%"),
            )
        )
        records = rows.all()
        for secret_ref_id, purged_at in records:
            already_purged = purged_at is not None
            try:
                self.store.delete(tenant_id, secret_ref_id)
            except Exception:  # noqa: BLE001 - 失敗は durable に記録し次回再試行
                logger.warning(
                    "gc-orphans purge failed",
                    extra={"tenant_id": tenant_id, "secret_ref_id": str(secret_ref_id)},
                )
                if not already_purged:
                    await self.session.execute(
                        update(SecretRef)
                        .where(SecretRef.tenant_id == tenant_id, SecretRef.id == secret_ref_id)
                        .values(purge_attempts=SecretRef.purge_attempts + 1)
                    )
                    await self.session.commit()
                    report.purge_failed.append(str(secret_ref_id))
                continue
            if already_purged:
                # 既に purged 確定済 → store.delete は backstop (再作成 material を除去)。状態変更なし。
                continue
            result = await self.session.execute(
                update(SecretRef)
                .where(
                    SecretRef.tenant_id == tenant_id,
                    SecretRef.id == secret_ref_id,
                    SecretRef.status == "revoked",
                    SecretRef.material_purged_at.is_(None),
                )
                .values(material_state="purged", material_purged_at=datetime.now(UTC))
            )
            if cast("Any", result).rowcount == 1:
                await self._audit(
                    tenant_id=tenant_id,
                    event_type="secret_material_purged",
                    secret_ref_id=secret_ref_id,
                    reason="gc_orphans_purged",
                )
                report.purged.append(str(secret_ref_id))
            await self.session.commit()

    async def _tombstone_writing_orphans(
        self, tenant_id: int, writing_grace_seconds: int, report: ReconciliationReport
    ) -> None:
        cutoff = datetime.now(UTC) - timedelta(seconds=writing_grace_seconds)
        rows = await self.session.execute(
            select(SecretRef.id).where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.material_state == "writing",
                SecretRef.status == "pending",
                SecretRef.updated_at < cutoff,
                SecretRef.secret_uri.like(f"{_LOCAL_URI_PREFIX}%"),
            )
        )
        ids = [row[0] for row in rows.all()]
        for secret_ref_id in ids:
            # row を delete せず revoked+purging に tombstone する。DB owner を残すことで late writer の
            # promote (WHERE pending+writing) は 0 rows となり、material は revoke-orphan purge 経路が
            # durable に削除する (Codex F2: row 消滅だと owner なし orphan material が残る)。
            result = await self.session.execute(
                update(SecretRef)
                .where(
                    SecretRef.tenant_id == tenant_id,
                    SecretRef.id == secret_ref_id,
                    SecretRef.status == "pending",
                    SecretRef.material_state == "writing",
                )
                .values(
                    status="revoked",
                    material_state="purging",
                    revoked_at=datetime.now(UTC),
                )
            )
            if cast("Any", result).rowcount == 1:
                await self._audit(
                    tenant_id=tenant_id,
                    event_type="secret_material_orphan_tombstoned",
                    secret_ref_id=secret_ref_id,
                    reason="gc_orphans_writing_tombstoned",
                )
                report.rolled_back.append(str(secret_ref_id))
                await self.session.commit()
            else:
                # 競合で状態が変わっていた (register/rotate 完了等) → no-op。
                await self.session.rollback()


__all__ = [
    "MaterialReconciliationService",
    "ReconciliationReport",
]
