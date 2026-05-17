"""Secret rotation service (Sprint 11.5 batch 3b、BL-0138).

`secret_refs.status` enum (`pending` / `active` / `deprecated` / `revoked`) 上の
rotation state transitions を service layer で encapsulate.

Rotation flow (ADR-00006 + DD-06 既 accepted):
1. **Issue new**: pending secret_ref を create (admin SOPS rotation 後)
2. **Promote**: pending → active (旧 active を deprecated に同 transaction で降格)
3. **Revoke old**: deprecated → revoked (TTL or manual)
4. **Rollback (optional)**: deprecated → active (incident rollback、revoked からは禁止)

Canary preflight (AC-HARD-02 trace):
- rotation 前に新 secret_ref metadata に canary pattern (sk-/ghp_ 等) が含まれないか check
- 含まれる場合 deny (rotation 経路で raw secret 流入を防止)

CRITICAL invariant trace:
- SecretBroker boundary: 本 service は status / timestamp 操作のみ、raw secret 値は触らない
- atomic claim: rotation transitions は同一 transaction 内で実行 (旧 active と新 pending の
  state 不整合期間を排除)
- self-approval 禁止: rotation を実行する actor は admin、自己承認不可
- 5+ source enum integrity: SecretRefStatus Literal (4 値) と完全整合
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.secret_ref import SecretRef
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

logger = logging.getLogger(__name__)

RotationOperation = Literal[
    "issue_new", "promote", "revoke", "rollback", "dry_run"
]
"""Sprint 11.5 batch 3b rotation operation enum (5 種、Literal で固定)."""

ROTATION_OPERATIONS: Final[frozenset[str]] = frozenset(
    {"issue_new", "promote", "revoke", "rollback", "dry_run"}
)


@dataclass(frozen=True, slots=True)
class RotationDrillResult:
    """Rotation drill execution result (JSON serializable via asdict)."""

    timestamp: str
    operation: RotationOperation
    dry_run: bool
    success: bool
    old_secret_ref_id: str | None
    new_secret_ref_id: str | None
    transitions: tuple[str, ...]  # "old:active→deprecated" 等
    plan_or_log: str
    error_message: str | None = None


class RotationError(ValueError):
    """Rotation guard violation."""


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _canary_preflight(metadata: dict[str, object] | None) -> None:
    """rotation 前 metadata canary pattern check.

    AC-HARD-02 secret_canary_no_leak 経路統合: 新 secret_ref の metadata に
    raw secret pattern (sk-, ghp_, AGE-SECRET 等) が含まれる場合 deny.
    """

    if metadata is None or not metadata:
        return
    try:
        assert_no_raw_secret(metadata)
    except ValueError as exc:
        raise RotationError(
            f"canary preflight rejected metadata (canary pattern hit): {exc}"
        ) from exc


def _validate_operation(op: str) -> RotationOperation:
    if op not in ROTATION_OPERATIONS:
        raise RotationError(
            f"invalid rotation operation: {op!r}, must be one of {sorted(ROTATION_OPERATIONS)}"
        )
    return op  # type: ignore[return-value]


class SecretRotationService:
    """`secret_refs.status` transitions + atomic transaction guard.

    本 service は **status / timestamp** のみ操作、raw secret 値は SOPS age key
    経由で admin が separately 配置済前提 (本 service は metadata + state machine).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
            return
        await assert_tenant_context(self.session, tenant_id)

    async def _fetch_secret_ref(
        self, tenant_id: int, secret_ref_id: UUID
    ) -> SecretRef | None:
        return cast(
            "SecretRef | None",
            await self.session.scalar(
                select(SecretRef).where(
                    SecretRef.tenant_id == tenant_id,
                    SecretRef.id == secret_ref_id,
                )
            ),
        )

    async def issue_new(
        self,
        *,
        tenant_id: int,
        new_secret_ref_id: UUID,
        metadata: dict[str, object] | None = None,
    ) -> RotationDrillResult:
        """新 secret_ref を `pending` status で create する scenario.

        本 method は **既存 pending secret_ref の検証のみ** (実際の row insert は
        admin SOPS rotation 経路で別途完了済前提). canary preflight を pass する.
        """

        _canary_preflight(metadata)
        await self._ensure_tenant_context(tenant_id)

        existing = await self._fetch_secret_ref(tenant_id, new_secret_ref_id)
        if existing is None:
            return RotationDrillResult(
                timestamp=_now_utc().isoformat(),
                operation="issue_new",
                dry_run=False,
                success=False,
                old_secret_ref_id=None,
                new_secret_ref_id=str(new_secret_ref_id),
                transitions=(),
                plan_or_log="new_secret_ref not found",
                error_message="not_found",
            )
        if existing.status != "pending":
            return RotationDrillResult(
                timestamp=_now_utc().isoformat(),
                operation="issue_new",
                dry_run=False,
                success=False,
                old_secret_ref_id=None,
                new_secret_ref_id=str(new_secret_ref_id),
                transitions=(),
                plan_or_log=f"expected status=pending, got {existing.status}",
                error_message="invalid_status",
            )

        return RotationDrillResult(
            timestamp=_now_utc().isoformat(),
            operation="issue_new",
            dry_run=False,
            success=True,
            old_secret_ref_id=None,
            new_secret_ref_id=str(new_secret_ref_id),
            transitions=("new:pending (verified)",),
            plan_or_log="canary preflight passed, new secret_ref in pending status",
        )

    async def promote(
        self,
        *,
        tenant_id: int,
        old_secret_ref_id: UUID,
        new_secret_ref_id: UUID,
    ) -> RotationDrillResult:
        """rotation `pending → active`、旧 active → deprecated (atomic transaction).

        順序:
        1. old (active) を deprecated に降格 + deprecated_at set
        2. new (pending) を active に promote
        全 update は同一 transaction、partial failure で全 rollback.
        """

        await self._ensure_tenant_context(tenant_id)
        timestamp = _now_utc()
        timestamp_iso = timestamp.isoformat()

        old_ref = await self._fetch_secret_ref(tenant_id, old_secret_ref_id)
        new_ref = await self._fetch_secret_ref(tenant_id, new_secret_ref_id)

        if old_ref is None or new_ref is None:
            return RotationDrillResult(
                timestamp=timestamp_iso,
                operation="promote",
                dry_run=False,
                success=False,
                old_secret_ref_id=str(old_secret_ref_id),
                new_secret_ref_id=str(new_secret_ref_id),
                transitions=(),
                plan_or_log="secret_ref not found",
                error_message="not_found",
            )
        if old_ref.status != "active":
            return RotationDrillResult(
                timestamp=timestamp_iso,
                operation="promote",
                dry_run=False,
                success=False,
                old_secret_ref_id=str(old_secret_ref_id),
                new_secret_ref_id=str(new_secret_ref_id),
                transitions=(),
                plan_or_log=f"old must be active, got {old_ref.status}",
                error_message="invalid_old_status",
            )
        if new_ref.status != "pending":
            return RotationDrillResult(
                timestamp=timestamp_iso,
                operation="promote",
                dry_run=False,
                success=False,
                old_secret_ref_id=str(old_secret_ref_id),
                new_secret_ref_id=str(new_secret_ref_id),
                transitions=(),
                plan_or_log=f"new must be pending, got {new_ref.status}",
                error_message="invalid_new_status",
            )

        # Atomic transaction: 同一 commit で old→deprecated + new→active.
        await self.session.execute(
            update(SecretRef)
            .where(SecretRef.tenant_id == tenant_id, SecretRef.id == old_secret_ref_id)
            .values(status="deprecated", deprecated_at=timestamp, updated_at=timestamp)
        )
        await self.session.execute(
            update(SecretRef)
            .where(SecretRef.tenant_id == tenant_id, SecretRef.id == new_secret_ref_id)
            .values(status="active", updated_at=timestamp)
        )

        logger.info(
            "secret_rotation_promote",
            extra={
                "tenant_id": tenant_id,
                "old_secret_ref_id": str(old_secret_ref_id),
                "new_secret_ref_id": str(new_secret_ref_id),
            },
        )

        return RotationDrillResult(
            timestamp=timestamp_iso,
            operation="promote",
            dry_run=False,
            success=True,
            old_secret_ref_id=str(old_secret_ref_id),
            new_secret_ref_id=str(new_secret_ref_id),
            transitions=("old:active→deprecated", "new:pending→active"),
            plan_or_log="rotation promote completed",
        )

    async def revoke(
        self, *, tenant_id: int, secret_ref_id: UUID
    ) -> RotationDrillResult:
        """`deprecated → revoked` (TTL or manual).

        revoked は terminal、再 active 化不可 (rollback path で別 secret_ref 必要).
        """

        await self._ensure_tenant_context(tenant_id)
        timestamp = _now_utc()
        timestamp_iso = timestamp.isoformat()

        ref = await self._fetch_secret_ref(tenant_id, secret_ref_id)
        if ref is None:
            return RotationDrillResult(
                timestamp=timestamp_iso,
                operation="revoke",
                dry_run=False,
                success=False,
                old_secret_ref_id=str(secret_ref_id),
                new_secret_ref_id=None,
                transitions=(),
                plan_or_log="secret_ref not found",
                error_message="not_found",
            )
        if ref.status != "deprecated":
            return RotationDrillResult(
                timestamp=timestamp_iso,
                operation="revoke",
                dry_run=False,
                success=False,
                old_secret_ref_id=str(secret_ref_id),
                new_secret_ref_id=None,
                transitions=(),
                plan_or_log=f"must be deprecated, got {ref.status}",
                error_message="invalid_status",
            )

        await self.session.execute(
            update(SecretRef)
            .where(SecretRef.tenant_id == tenant_id, SecretRef.id == secret_ref_id)
            .values(status="revoked", revoked_at=timestamp, updated_at=timestamp)
        )

        logger.info(
            "secret_rotation_revoke",
            extra={"tenant_id": tenant_id, "secret_ref_id": str(secret_ref_id)},
        )

        return RotationDrillResult(
            timestamp=timestamp_iso,
            operation="revoke",
            dry_run=False,
            success=True,
            old_secret_ref_id=str(secret_ref_id),
            new_secret_ref_id=None,
            transitions=("deprecated→revoked",),
            plan_or_log="secret_ref revoked",
        )

    async def rollback(
        self,
        *,
        tenant_id: int,
        deprecated_secret_ref_id: UUID,
        currently_active_secret_ref_id: UUID,
    ) -> RotationDrillResult:
        """incident rollback: deprecated → active 復元、currently active → deprecated 降格.

        revoked からの復元は禁止 (revoked は terminal、ADR-00006).
        """

        await self._ensure_tenant_context(tenant_id)
        timestamp = _now_utc()
        timestamp_iso = timestamp.isoformat()

        deprecated_ref = await self._fetch_secret_ref(tenant_id, deprecated_secret_ref_id)
        active_ref = await self._fetch_secret_ref(
            tenant_id, currently_active_secret_ref_id
        )
        if deprecated_ref is None or active_ref is None:
            return RotationDrillResult(
                timestamp=timestamp_iso,
                operation="rollback",
                dry_run=False,
                success=False,
                old_secret_ref_id=str(currently_active_secret_ref_id),
                new_secret_ref_id=str(deprecated_secret_ref_id),
                transitions=(),
                plan_or_log="secret_ref not found",
                error_message="not_found",
            )
        if deprecated_ref.status != "deprecated":
            return RotationDrillResult(
                timestamp=timestamp_iso,
                operation="rollback",
                dry_run=False,
                success=False,
                old_secret_ref_id=str(currently_active_secret_ref_id),
                new_secret_ref_id=str(deprecated_secret_ref_id),
                transitions=(),
                plan_or_log=(
                    f"rollback target must be deprecated, got {deprecated_ref.status}"
                ),
                error_message="invalid_rollback_target_status",
            )
        if active_ref.status != "active":
            return RotationDrillResult(
                timestamp=timestamp_iso,
                operation="rollback",
                dry_run=False,
                success=False,
                old_secret_ref_id=str(currently_active_secret_ref_id),
                new_secret_ref_id=str(deprecated_secret_ref_id),
                transitions=(),
                plan_or_log=f"current active expected, got {active_ref.status}",
                error_message="invalid_current_status",
            )

        # Atomic rollback: currently_active → deprecated、deprecated_secret_ref → active.
        await self.session.execute(
            update(SecretRef)
            .where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.id == currently_active_secret_ref_id,
            )
            .values(status="deprecated", deprecated_at=timestamp, updated_at=timestamp)
        )
        await self.session.execute(
            update(SecretRef)
            .where(
                SecretRef.tenant_id == tenant_id,
                SecretRef.id == deprecated_secret_ref_id,
            )
            .values(status="active", deprecated_at=None, updated_at=timestamp)
        )

        logger.info(
            "secret_rotation_rollback",
            extra={
                "tenant_id": tenant_id,
                "restored_secret_ref_id": str(deprecated_secret_ref_id),
                "demoted_secret_ref_id": str(currently_active_secret_ref_id),
            },
        )

        return RotationDrillResult(
            timestamp=timestamp_iso,
            operation="rollback",
            dry_run=False,
            success=True,
            old_secret_ref_id=str(currently_active_secret_ref_id),
            new_secret_ref_id=str(deprecated_secret_ref_id),
            transitions=("current_active→deprecated", "deprecated→active"),
            plan_or_log="rotation rolled back",
        )

    async def dry_run_plan(
        self,
        *,
        tenant_id: int,
        operation: RotationOperation,
        old_secret_ref_id: UUID | None = None,
        new_secret_ref_id: UUID | None = None,
        metadata: dict[str, object] | None = None,
    ) -> RotationDrillResult:
        """dry-run mode: status transitions plan を返す、実 DB update なし.

        canary preflight は dry-run でも実行 (operator 計画段階で reject).
        """

        _validate_operation(operation)
        if metadata:
            _canary_preflight(metadata)
        await self._ensure_tenant_context(tenant_id)
        timestamp_iso = _now_utc().isoformat()

        plan_lines: list[str] = []
        transitions: list[str] = []
        if operation == "issue_new" and new_secret_ref_id is not None:
            plan_lines.append(f"verify new {new_secret_ref_id} status=pending")
            transitions.append("new:pending (planned)")
        elif operation == "promote" and old_secret_ref_id and new_secret_ref_id:
            plan_lines.append(f"update {old_secret_ref_id}: active→deprecated")
            plan_lines.append(f"update {new_secret_ref_id}: pending→active")
            transitions.extend(("old:active→deprecated", "new:pending→active"))
        elif operation == "revoke" and old_secret_ref_id:
            plan_lines.append(f"update {old_secret_ref_id}: deprecated→revoked")
            transitions.append("deprecated→revoked")
        elif operation == "rollback" and old_secret_ref_id and new_secret_ref_id:
            plan_lines.append(
                f"update {new_secret_ref_id}: current_active→deprecated"
            )
            plan_lines.append(f"update {old_secret_ref_id}: deprecated→active")
            transitions.extend(
                ("current_active→deprecated", "deprecated→active")
            )

        return RotationDrillResult(
            timestamp=timestamp_iso,
            operation=operation,
            dry_run=True,
            success=True,
            old_secret_ref_id=str(old_secret_ref_id) if old_secret_ref_id else None,
            new_secret_ref_id=str(new_secret_ref_id) if new_secret_ref_id else None,
            transitions=tuple(transitions),
            plan_or_log="\n".join(plan_lines) or f"{operation} plan",
        )


__all__ = [
    "ROTATION_OPERATIONS",
    "RotationDrillResult",
    "RotationError",
    "RotationOperation",
    "SecretRotationService",
]
