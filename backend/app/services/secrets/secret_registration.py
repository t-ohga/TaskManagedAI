"""SecretRegistrationService: crash-safe な secret material lifecycle 調停 (ADR-00058 / ADR-00059)。

raw material を ``LocalSecretStore`` (broker-owned、local backend) へ委譲しつつ、``secret_refs`` の
metadata row を **crash-safe な順序**で調停する。``rotation.py`` (status/timestamp のみ) とは責務分離。

**crash-safe 順序 (ADR-00058 finding-2)**:
1. secret_refs row を ``pending`` + ``material_state='writing'`` で INSERT/commit (DB が material
   owner の source of truth)
2. store へ raw 書込 (key = ``tenant_id + secret_ref_id``)
3. row を ``material_state='present'`` + (create 時) ``active`` 昇格 commit

途中 crash / store 失敗 / DB 失敗は ``material_state`` + ``material_reconciliation.gc_orphans`` で収束。

**create / rotate 分離**: 初回 create は present 後に active 昇格可。rotate は新 version を pending +
present のまま残し、``promote_rotated`` で ``secret.verify`` / dry-run / smoke 通過後に新 active +
旧 deprecated とする (未検証 material を active にしない)。

**revoke (rule §5)**: ``active`` / ``deprecated`` / ``pending`` → ``revoked`` を許容する新経路
(``rotation.py.revoke()`` の rotation 専用 deprecated→revoked は流用しない)。material 削除は revoked
確定後の別 step、best-effort + ``gc-orphans`` reconciliation で durable 収束。

**self-rotating credential は broker-managed 登録 reject** (案B の罠の構造防止)。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.secret_ref import SecretRef, SecretRefScope
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.secret_ref import SecretRefRepository
from backend.app.services.secrets.local_secret_store import LocalSecretStore
from backend.app.services.secrets.uri_pattern import secret_uri_backend

logger = logging.getLogger(__name__)


class SecretRegistrationError(Exception):
    """registration / rotation / revoke の一般エラー (raw material を message に含めない)。"""


class SecretRegistrationConflict(SecretRegistrationError):
    """期待 status と不一致 (concurrent transition / stale state)。"""


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _canary_preflight(metadata: dict[str, Any] | None) -> None:
    if metadata is None:
        return
    # DB CHECK は prohibited key を reject するが raw secret value pattern は reject しないため、
    # service 層で metadata の raw secret value を事前 reject (rotation.py と同方針)。
    assert_no_raw_secret(metadata)


class SecretRegistrationService:
    """broker-owned (local) material の crash-safe registration / rotation / revoke。

    本 service は admin lifecycle 操作 (taskhub secret create/rotate/revoke) として **自身で
    transaction 境界を所有** する (crash-safe durability のため pending row を store 書込前に commit
    する必要がある)。
    """

    def __init__(self, session: AsyncSession, store: LocalSecretStore) -> None:
        self.session = session
        self.store = store

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
            return
        await assert_tenant_context(self.session, tenant_id)

    async def _fetch(self, tenant_id: int, secret_ref_id: UUID) -> SecretRef | None:
        return cast(
            "SecretRef | None",
            await self.session.scalar(
                select(SecretRef).where(
                    SecretRef.tenant_id == tenant_id,
                    SecretRef.id == secret_ref_id,
                )
            ),
        )

    async def _audit(
        self, *, tenant_id: int, event_type: str, payload: dict[str, Any]
    ) -> None:
        repo = AuditEventRepository(self.session)
        await repo.append(tenant_id=tenant_id, event_type=event_type, payload=payload)

    # ---- create ----

    async def register(
        self,
        *,
        tenant_id: int,
        scope: SecretRefScope,
        name: str,
        version: str,
        owner_actor_id: UUID,
        raw_material: bytes,
        allowed_consumers: list[str],
        allowed_operations: list[str],
        backend: str = "local",
        metadata: dict[str, Any] | None = None,
    ) -> SecretRef:
        """新 secret を crash-safe に登録し active 昇格する (pending+writing→store→present+active)。"""
        if backend != "local":
            raise SecretRegistrationError(
                "Phase 0 SecretRegistrationService manages local backend only; "
                "sops material is placed by admin SOPS rotation"
            )
        _canary_preflight(metadata)
        self._reject_self_rotating(metadata)
        if not allowed_consumers or not allowed_operations:
            raise SecretRegistrationError(
                "active secret requires non-empty allowed_consumers and allowed_operations"
            )
        await self._ensure_tenant_context(tenant_id)

        repo = SecretRefRepository(self.session)
        # marker fresh-init / marker-loss-recovery 判定は create_metadata (新 local row flush) の前に行う
        # (Codex R23-F1): 新 row 後だと has_local_secret_refs が常に True になり fresh-init も refuse する。
        await self._assert_marker_init_safe(repo, tenant_id)
        row = await repo.create_metadata(
            tenant_id=tenant_id,
            backend=backend,
            scope=scope,
            name=name,
            version=version,
            status="pending",
            owner_actor_id=owner_actor_id,
            allowed_consumers=allowed_consumers,
            allowed_operations=allowed_operations,
            metadata=metadata,
            material_state="writing",
        )
        secret_ref_id = row.id
        # (0) DB row commit の **前** に backend marker を pin する (Codex R14-F1): marker は store() でも
        #     pin されるが、「row commit 後 / store() 前」の crash で marker 不在のまま row が残ると、後続
        #     gc の delete() (marker 必須・fail-closed) で永久に purge 収束できなくなる。marker は非 secret。
        self.store.ensure_initialized()
        # (1) pending+writing を durable 化してから store 書込 (crash-safe: store のみ成功で row 無し
        #     を防ぐ。逆順だと orphan material を検出する DB source of truth が無い)。
        await self.session.commit()

        # (2) store へ raw material 書込 (key = tenant_id + secret_ref_id)。
        self.store.store(tenant_id, secret_ref_id, raw_material)

        # (3) present + active へ昇格 (conditional: pending+writing からのみ)。
        result = await self.session.execute(
            update(SecretRef)
            .where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.id == secret_ref_id,
                SecretRef.status == "pending",
                SecretRef.material_state == "writing",
            )
            .values(status="active", material_state="present")
        )
        if cast("Any", result).rowcount != 1:
            await self.session.rollback()
            # row が reconcile で revoked+purging へ tombstone された等で promote 不能。書いた material が
            # DB owner を失わないよう best-effort cleanup (Codex F2: late writer orphan)。失敗しても
            # tombstone 済 row を gc-orphans が durable に purge する。
            self._best_effort_cleanup_material(tenant_id, secret_ref_id)
            raise SecretRegistrationConflict(
                "register promote failed: row not in pending+writing state"
            )
        await self._audit(
            tenant_id=tenant_id,
            event_type="secret_registered",
            payload={
                "secret_ref_id": str(secret_ref_id),
                "scope": scope,
                "name": name,
                "version": version,
                "backend": backend,
                "reason_code": "secret_registered",
            },
        )
        await self.session.commit()
        refreshed = await self._fetch(tenant_id, secret_ref_id)
        if refreshed is None:  # pragma: no cover - just-written row must exist
            raise SecretRegistrationError("secret_ref disappeared after write")
        return refreshed

    # ---- rotate (place new-version material, leave pending+present) ----

    async def rotate(
        self,
        *,
        tenant_id: int,
        old_secret_ref_id: UUID,
        new_version: str,
        owner_actor_id: UUID,
        raw_material: bytes,
        allowed_consumers: list[str],
        allowed_operations: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> SecretRef:
        """新 version material を crash-safe に配置し pending+present で残す (active 化しない)。"""
        _canary_preflight(metadata)
        self._reject_self_rotating(metadata)
        await self._ensure_tenant_context(tenant_id)

        old = await self._fetch(tenant_id, old_secret_ref_id)
        if old is None:
            raise SecretRegistrationError("old secret_ref not found")
        if secret_uri_backend(old.secret_uri) != "local":
            raise SecretRegistrationError("rotate manages local backend only")
        # rotate precondition gate (Codex R7-F1): 新 version を pending+present で配置する前に old が
        # promote 可能な状態か fail-closed 検証する。promote_rotated は old.status='active' を必須に
        # するため、非 active / 未 present の old から rotate すると、新 row が **永久に promote 不能な
        # pending+present orphan** になる (gc-orphans は pending+writing のみ tombstone するため durable
        # に残り、material at-rest 保持 + (tenant,scope,name) pending≤1 index を占有する)。register と
        # 対称に、write 前 (create_metadata / store.store 前) に reject する。
        if old.status != "active":
            raise SecretRegistrationConflict(
                "rotate requires the old secret_ref to be active "
                f"(got status {old.status!r})"
            )
        if old.material_state != "present":
            raise SecretRegistrationConflict(
                "rotate requires the old secret_ref material_state='present' "
                f"(got {old.material_state!r})"
            )
        if not allowed_consumers or not allowed_operations:
            raise SecretRegistrationError(
                "rotated secret requires non-empty allowed_consumers and allowed_operations"
            )

        repo = SecretRefRepository(self.session)
        # marker-loss-recovery refuse (Codex R23-F1)。rotate は old local material が前提のため、marker 不在は
        # 常に recovery (operator action 要)。create_metadata の前 (新 row flush 前) に判定する。
        await self._assert_marker_init_safe(repo, tenant_id)
        row = await repo.create_metadata(
            tenant_id=tenant_id,
            backend="local",
            scope=old.scope,
            name=old.name,
            version=new_version,
            status="pending",
            owner_actor_id=owner_actor_id,
            allowed_consumers=allowed_consumers,
            allowed_operations=allowed_operations,
            metadata=metadata,
            material_state="writing",
            rotated_from_id=old_secret_ref_id,
        )
        new_id = row.id
        # DB row commit の前に backend marker を pin する (Codex R14-F1、register と同様 crash-window 対策)。
        self.store.ensure_initialized()
        await self.session.commit()

        self.store.store(tenant_id, new_id, raw_material)

        # present 化を **old が現在も active+present であること** に atomic 条件付けする (Codex R8-F1)。
        # §215 の precondition gate は fetch 時点の stale precheck に過ぎず、precheck→ここの間に別操作が
        # old を promote/revoke/deprecate すると、本 UPDATE が new の status/material_state しか見ないため
        # new は pending+present として残り、promote_rotated (old=active 必須) が永久に失敗 + gc-orphans
        # (pending+writing のみ tombstone) でも回収されない durable orphan になる。old を非相関 EXISTS で
        # 同一文 re-validate し、不一致なら UPDATE が 0 行 → new は pending+writing のまま (gc-orphans が
        # tombstone) + material を best-effort cleanup + conflict を返す。
        old_ref = aliased(SecretRef)
        old_still_active = (
            select(old_ref.id)
            .where(
                old_ref.tenant_id == tenant_id,
                old_ref.id == old_secret_ref_id,
                old_ref.status == "active",
                old_ref.material_state == "present",
            )
            .exists()
        )
        result = await self.session.execute(
            update(SecretRef)
            .where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.id == new_id,
                SecretRef.status == "pending",
                SecretRef.material_state == "writing",
                old_still_active,
            )
            .values(material_state="present")  # status は pending のまま (未検証は active 化しない)
        )
        if cast("Any", result).rowcount != 1:
            await self.session.rollback()
            self._best_effort_cleanup_material(tenant_id, new_id)
            raise SecretRegistrationConflict(
                "rotate material placement failed: new not in pending+writing "
                "or old no longer active+present"
            )
        await self._audit(
            tenant_id=tenant_id,
            event_type="secret_rotation_material_placed",
            payload={
                "secret_ref_id": str(new_id),
                "rotated_from_id": str(old_secret_ref_id),
                "scope": old.scope,
                "name": old.name,
                "version": new_version,
                "reason_code": "rotation_material_placed",
            },
        )
        await self.session.commit()
        refreshed = await self._fetch(tenant_id, new_id)
        if refreshed is None:  # pragma: no cover - just-written row must exist
            raise SecretRegistrationError("secret_ref disappeared after write")
        return refreshed

    async def promote_rotated(
        self,
        *,
        tenant_id: int,
        old_secret_ref_id: UUID,
        new_secret_ref_id: UUID,
    ) -> None:
        """verify/smoke 通過後に新 version active + 旧 version deprecated (material_state='present' 必須)。

        新 version の ``material_state='present'`` を WHERE に含め、未検証 (writing) material を
        active にしない (ADR-00058 finding-2 の negative case)。
        """
        await self._ensure_tenant_context(tenant_id)
        old = await self._fetch(tenant_id, old_secret_ref_id)
        new = await self._fetch(tenant_id, new_secret_ref_id)
        if old is None or new is None:
            raise SecretRegistrationError("secret_ref not found")
        if old.scope != new.scope or old.name != new.name:
            raise SecretRegistrationError("old/new scope or name mismatch")
        if new.rotated_from_id != old_secret_ref_id:
            raise SecretRegistrationError("new.rotated_from_id must point to old")
        now = _now_utc()

        # 旧 active → deprecated (atomic claim、expected status)。
        old_result = await self.session.execute(
            update(SecretRef)
            .where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.id == old_secret_ref_id,
                SecretRef.status == "active",
            )
            .values(status="deprecated", deprecated_at=now)
        )
        # 新 pending+present → active (material_state='present' 必須 = 未検証 reject)。
        new_result = await self.session.execute(
            update(SecretRef)
            .where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.id == new_secret_ref_id,
                SecretRef.status == "pending",
                SecretRef.material_state == "present",
            )
            .values(status="active")
        )
        if cast("Any", old_result).rowcount != 1 or cast("Any", new_result).rowcount != 1:
            await self.session.rollback()
            raise SecretRegistrationConflict(
                "promote_rotated failed: old must be active, new must be pending+present"
            )
        await self._audit(
            tenant_id=tenant_id,
            event_type="secret_rotation_promoted",
            payload={
                "old_secret_ref_id": str(old_secret_ref_id),
                "new_secret_ref_id": str(new_secret_ref_id),
                "reason_code": "rotation_promoted",
            },
        )
        await self.session.commit()

    # ---- revoke (rule §5) + best-effort purge ----

    async def revoke(
        self,
        *,
        tenant_id: int,
        secret_ref_id: UUID,
    ) -> SecretRef:
        """rule §5 (active/deprecated/pending → revoked)。material 削除は revoked 確定後の別 step。

        local backend は ``material_state='purging'`` にし best-effort purge (失敗時は
        ``material_purged_at IS NULL`` のまま gc-orphans が再試行)。非 local backend は broker-owned
        material を持たないため ``material_purged_at=now()`` を即 set (purged)。
        """
        await self._ensure_tenant_context(tenant_id)
        ref = await self._fetch(tenant_id, secret_ref_id)
        if ref is None:
            raise SecretRegistrationError("secret_ref not found")
        if ref.status == "revoked":
            raise SecretRegistrationConflict("secret_ref already revoked (terminal)")

        now = _now_utc()
        is_local = secret_uri_backend(ref.secret_uri) == "local"
        if is_local:
            # revoked + purging (purge 待ち)、material_purged_at は NULL のまま gc-orphans 対象。
            values: dict[str, Any] = {
                "status": "revoked",
                "revoked_at": now,
                "material_state": "purging",
            }
        else:
            # broker-owned material 無し → 即 purged 扱い (material_purged_at non-NULL で初めて真)。
            values = {
                "status": "revoked",
                "revoked_at": now,
                "material_state": "purged",
                "material_purged_at": now,
            }
        result = await self.session.execute(
            update(SecretRef)
            .where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.id == secret_ref_id,
                SecretRef.status.in_(("active", "deprecated", "pending")),
            )
            .values(**values)
        )
        if cast("Any", result).rowcount != 1:
            await self.session.rollback()
            raise SecretRegistrationConflict(
                "revoke failed: status not in (active, deprecated, pending)"
            )
        await self._audit(
            tenant_id=tenant_id,
            event_type="secret_revoked",
            payload={
                "secret_ref_id": str(secret_ref_id),
                "scope": ref.scope,
                "name": ref.name,
                "backend": "local" if is_local else "sops",
                "reason_code": "secret_revoked",
            },
        )
        # revoked を durable 化してから material 削除 (DB commit と store delete の非 atomicity を
        # reconciliation で吸収。ここで crash しても revoked は durable に「未 purge」)。
        await self.session.commit()

        if is_local:
            await self._best_effort_purge(tenant_id, secret_ref_id)

        refreshed = await self._fetch(tenant_id, secret_ref_id)
        if refreshed is None:  # pragma: no cover - just-written row must exist
            raise SecretRegistrationError("secret_ref disappeared after write")
        return refreshed

    async def _best_effort_purge(self, tenant_id: int, secret_ref_id: UUID) -> None:
        """local material を削除し purged 化する。失敗は purge_attempts++ で gc-orphans 再試行に委ねる。"""
        try:
            self.store.delete(tenant_id, secret_ref_id)
        except Exception as exc:  # noqa: BLE001 - 失敗は durable に記録し再試行
            logger.warning(
                "best-effort purge failed; deferring to gc-orphans",
                extra={"tenant_id": tenant_id, "secret_ref_id": str(secret_ref_id)},
            )
            await self.session.execute(
                update(SecretRef)
                .where(
                    SecretRef.tenant_id == tenant_id,
                    SecretRef.id == secret_ref_id,
                )
                .values(purge_attempts=SecretRef.purge_attempts + 1)
            )
            await self.session.commit()
            _ = exc
            return
        await self.session.execute(
            update(SecretRef)
            .where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.id == secret_ref_id,
                SecretRef.status == "revoked",
                SecretRef.material_purged_at.is_(None),
            )
            .values(material_state="purged", material_purged_at=_now_utc())
        )
        await self.session.commit()

    def _best_effort_cleanup_material(self, tenant_id: int, secret_ref_id: UUID) -> None:
        """promote 失敗時に書き込んだ material を best-effort で削除する (Codex F2: late writer orphan)。

        失敗しても DB owner row は reconcile で revoked+purging に残るため gc-orphans が durable に purge
        する。よって本 cleanup は best-effort で良い (例外を握り潰す)。
        """
        try:
            self.store.delete(tenant_id, secret_ref_id)
        except Exception:  # noqa: BLE001 - best-effort、durable backstop は gc-orphans
            logger.warning(
                "best-effort material cleanup after promote failure failed; gc-orphans will reconcile",
                extra={"tenant_id": tenant_id, "secret_ref_id": str(secret_ref_id)},
            )

    async def _assert_marker_init_safe(
        self, repo: SecretRefRepository, tenant_id: int
    ) -> None:
        """backend marker の fresh first-init と marker-loss-recovery を区別する (Codex R23-F1)。

        marker 不在を ``ensure_initialized()`` が無条件に現在 backend で再 pin すると、keyring 一時無効時に
        ``file`` を新 marker として書き、以後 delete が旧 keyring material を no-op で purged 化する
        false-purged になる。**local secret_ref が既に存在するのに marker が無い場合 = marker-loss recovery**
        として refuse し、operator が元 backend を復元/検証してからの登録を要求する。marker 存在時は
        ``ensure_initialized()`` が drift を verify する。fresh first-store (marker 無 + local row 無) のみ通す。
        """
        if self.store.is_initialized():
            return
        if await repo.has_local_secret_refs(tenant_id):
            raise SecretRegistrationError(
                "backend marker missing but local secret_refs already exist (marker-loss recovery); "
                "restore/verify the original backend before registering new local material"
            )

    @staticmethod
    def _reject_self_rotating(metadata: dict[str, Any] | None) -> None:
        """self-rotating / host-ambient credential を broker-managed 登録すると reject (案B 罠防止)。

        CLI サブスク OAuth (self-rotating) は host-ambient で CLI が所有する。broker-managed store
        へ登録すると refresh で即 stale になり全 run 失敗するため、構造的に禁止する。
        """
        if metadata is None:
            return
        if metadata.get("self_rotating") is True:
            raise SecretRegistrationError(
                "self-rotating credentials must not be broker-managed; use host-ambient supply"
            )
        if metadata.get("credential_supply_mode") == "host_ambient":
            raise SecretRegistrationError(
                "host-ambient credentials are owned by the CLI; do not register them in the broker store"
            )


__all__ = [
    "SecretRegistrationConflict",
    "SecretRegistrationError",
    "SecretRegistrationService",
]
