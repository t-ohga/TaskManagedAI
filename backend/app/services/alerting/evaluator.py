"""Alert evaluator (Sprint 11.5 batch 2、BL-0135).

4 alert kind の評価 + Notification emit + 24h dedup.

dedup pattern (plan v1 §設計判断 line 40 + plan-reviewer MED-1 adopt):
- NotificationEvent.payload JSONB に `dedup_key` を含め、`payload->>'dedup_key'` +
  24h `created_at` filter で SELECT existence check、なければ emit。
- DB CHECK / column 追加なし (既存 NotificationEvent schema 不変、ADR Gate #2 回避).

trigger pattern (plan-reviewer MED-2 adopt):
- arq periodic task で 5-15 min interval evaluate (Sprint 11.5 batch 2 では
  scheduler 結線は scope 外、本 evaluator は library として exposable). Sprint 12
  以降で `backend/app/workers/main.py` の WorkerSettings に periodic task 登録予定.

CRITICAL invariant trace:
- AgentRun 16 状態 (`agent_runs.status` enum) を trigger 元として読む (既存不変)
- AC-KPI-03 `approval_wait_ms` median ≤4h 整合: approval_pending threshold = 4h
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import assert_tenant_context, set_tenant_context
from backend.app.db.models.notification_event import NotificationEvent
from backend.app.repositories.notification_event import NotificationEventRepository
from backend.app.services.alerting.kinds import (
    ALERT_KIND_VALUES,
    AlertKind,
    to_event_type,
)

logger = logging.getLogger(__name__)

# Default thresholds (Sprint 12 で config 化検討、本 batch は hardcode).
# AC-KPI-03 `approval_wait_ms` median ≤4h と整合.
DEFAULT_APPROVAL_PENDING_THRESHOLD: Final[timedelta] = timedelta(hours=4)
DEFAULT_RUN_FAILED_SPIKE_WINDOW: Final[timedelta] = timedelta(minutes=5)
DEFAULT_RUN_FAILED_SPIKE_THRESHOLD: Final[int] = 5  # 5 min で 5 件以上
DEFAULT_SECRET_ROTATION_DEFERRED_THRESHOLD: Final[timedelta] = timedelta(days=7)
DEFAULT_DEDUP_WINDOW: Final[timedelta] = timedelta(hours=24)


class ApprovalPendingAlertContext(BaseModel):
    """`approval_pending_overdue` alert context (Pydantic Field validation)."""

    approval_id: UUID
    requester_actor_id: UUID
    decider_actor_id: UUID | None = None
    action_class: str = Field(..., min_length=1, max_length=64)
    requested_at: datetime
    age_seconds: float = Field(..., ge=0.0)


class BudgetExceededAlertContext(BaseModel):
    """`budget_exceeded` alert context."""

    budget_scope: str = Field(..., min_length=1, max_length=64)
    spent_usd: float = Field(..., ge=0.0)
    limit_usd: float = Field(..., gt=0.0)
    overflow_usd: float = Field(..., ge=0.0)


class RunFailedSpikeAlertContext(BaseModel):
    """`run_failed_spike` alert context."""

    failed_count: int = Field(..., ge=1)
    window_seconds: float = Field(..., gt=0.0)
    project_id: UUID | None = None


class SecretRotationDeferredAlertContext(BaseModel):
    """`secret_rotation_deferred` alert context.

    secret_ref のみ参照、raw secret 値 / capability token は含めない (SecretBroker boundary).
    """

    secret_ref_id: UUID
    scope: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=128)
    deprecated_at: datetime
    age_seconds: float = Field(..., ge=0.0)


@dataclass(frozen=True, slots=True)
class AlertEmittedSummary:
    """Alert evaluator が emit した結果 summary."""

    kind: AlertKind
    emitted: bool
    dedup_hit: bool
    notification_event_id: UUID | None = None
    skip_reason: str | None = None


class AlertEvaluator:
    """Evaluate 4 alert kind + emit Notification + 24h dedup.

    `_emit_with_dedup` が `(tenant_id, event_type, dedup_key)` 24h window で
    重複 emit を suppress.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        dedup_window: timedelta = DEFAULT_DEDUP_WINDOW,
    ) -> None:
        self.session = session
        self._dedup_window = dedup_window

    async def emit_approval_pending_overdue(
        self,
        *,
        tenant_id: int,
        recipient_actor_id: UUID,
        context: ApprovalPendingAlertContext,
    ) -> AlertEmittedSummary:
        """Approval pending が threshold 超過した場合 emit."""

        dedup_key = f"approval:{context.approval_id}"
        payload = self._build_payload("approval_pending_overdue", dedup_key, context)
        return await self._emit_with_dedup(
            kind="approval_pending_overdue",
            tenant_id=tenant_id,
            recipient_actor_id=recipient_actor_id,
            dedup_key=dedup_key,
            payload=payload,
        )

    async def emit_budget_exceeded(
        self,
        *,
        tenant_id: int,
        recipient_actor_id: UUID,
        context: BudgetExceededAlertContext,
    ) -> AlertEmittedSummary:
        """Budget hard limit hit → emit."""

        dedup_key = f"budget:{context.budget_scope}"
        payload = self._build_payload("budget_exceeded", dedup_key, context)
        return await self._emit_with_dedup(
            kind="budget_exceeded",
            tenant_id=tenant_id,
            recipient_actor_id=recipient_actor_id,
            dedup_key=dedup_key,
            payload=payload,
        )

    async def emit_run_failed_spike(
        self,
        *,
        tenant_id: int,
        recipient_actor_id: UUID,
        context: RunFailedSpikeAlertContext,
    ) -> AlertEmittedSummary:
        """N min window で M+ failed → emit."""

        # dedup_key: project スコープ別 (None なら tenant スコープ).
        project_scope = str(context.project_id) if context.project_id else "tenant_all"
        dedup_key = f"run_failed_spike:{project_scope}"
        payload = self._build_payload("run_failed_spike", dedup_key, context)
        return await self._emit_with_dedup(
            kind="run_failed_spike",
            tenant_id=tenant_id,
            recipient_actor_id=recipient_actor_id,
            dedup_key=dedup_key,
            payload=payload,
        )

    async def emit_secret_rotation_deferred(
        self,
        *,
        tenant_id: int,
        recipient_actor_id: UUID,
        context: SecretRotationDeferredAlertContext,
    ) -> AlertEmittedSummary:
        """Secret rotation deprecated が threshold 超過 → emit.

        SecretBroker boundary 整合: secret_ref のみ参照、raw secret 値含めず.
        """

        dedup_key = f"secret_rotation:{context.secret_ref_id}"
        payload = self._build_payload("secret_rotation_deferred", dedup_key, context)
        return await self._emit_with_dedup(
            kind="secret_rotation_deferred",
            tenant_id=tenant_id,
            recipient_actor_id=recipient_actor_id,
            dedup_key=dedup_key,
            payload=payload,
        )

    def _build_payload(
        self,
        kind: AlertKind,
        dedup_key: str,
        context: BaseModel,
    ) -> dict[str, Any]:
        """Payload を構造化 (mode='json' で JSON serializable に強制)."""

        return {
            "alert_kind": kind,
            "dedup_key": dedup_key,
            "context": context.model_dump(mode="json"),
        }

    async def _emit_with_dedup(
        self,
        *,
        kind: AlertKind,
        tenant_id: int,
        recipient_actor_id: UUID,
        dedup_key: str,
        payload: dict[str, Any],
    ) -> AlertEmittedSummary:
        """24h window dedup + Notification emit.

        既存 24h within の同 `(tenant_id, event_type, dedup_key)` がある場合 skip.
        DB column 追加なし (payload JSONB probe、ADR Gate #2 回避).
        """

        if kind not in ALERT_KIND_VALUES:
            raise ValueError(f"invalid alert kind: {kind!r}")

        await self._ensure_tenant_context(tenant_id)

        event_type = to_event_type(kind)
        now = datetime.now(tz=UTC)
        window_start = now - self._dedup_window

        # dedup check: 24h within で同 event_type + dedup_key の Notification があるか
        # payload->>'dedup_key' JSONB probe (full table scan 許容、alert 件数少ない前提).
        existing = await self.session.scalar(
            select(func.count(NotificationEvent.id))
            .where(
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.event_type == event_type,
                NotificationEvent.created_at >= window_start,
                NotificationEvent.payload["dedup_key"].astext == dedup_key,
            )
        )
        if existing and existing > 0:
            logger.info(
                "alert_dedup_suppressed",
                extra={
                    "alert_kind": kind,
                    "tenant_id": tenant_id,
                    "dedup_key": dedup_key,
                    "existing_count": existing,
                },
            )
            return AlertEmittedSummary(
                kind=kind, emitted=False, dedup_hit=True, skip_reason="dedup_24h_window"
            )

        repo = NotificationEventRepository(self.session)
        event = await repo.append(
            tenant_id=tenant_id,
            event_type=event_type,
            payload=payload,
            recipient_actor_id=recipient_actor_id,
        )
        logger.info(
            "alert_emitted",
            extra={
                "alert_kind": kind,
                "tenant_id": tenant_id,
                "notification_event_id": str(event.id),
            },
        )
        return AlertEmittedSummary(
            kind=kind,
            emitted=True,
            dedup_hit=False,
            notification_event_id=event.id,
        )

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        """Repository pattern と同様の tenant context guard."""

        try:
            await assert_tenant_context(self.session, tenant_id)
        except Exception:  # noqa: BLE001 (boot/missing context は set で recover)
            await set_tenant_context(self.session, tenant_id)


def is_overdue(
    requested_at: datetime,
    *,
    now: datetime | None = None,
    threshold: timedelta = DEFAULT_APPROVAL_PENDING_THRESHOLD,
) -> bool:
    """Approval が threshold 超過したか判定 (test 用 helper)."""

    if now is None:
        now = datetime.now(tz=UTC)
    return (now - requested_at) > threshold


def count_recent_failures(
    failed_at_iter: Iterable[datetime],
    *,
    now: datetime | None = None,
    window: timedelta = DEFAULT_RUN_FAILED_SPIKE_WINDOW,
) -> int:
    """5 min window 内の failed count (test 用 helper)."""

    if now is None:
        now = datetime.now(tz=UTC)
    window_start = now - window
    return sum(1 for ts in failed_at_iter if ts >= window_start)


__all__ = [
    "AlertEmittedSummary",
    "AlertEvaluator",
    "ApprovalPendingAlertContext",
    "BudgetExceededAlertContext",
    "DEFAULT_APPROVAL_PENDING_THRESHOLD",
    "DEFAULT_DEDUP_WINDOW",
    "DEFAULT_RUN_FAILED_SPIKE_THRESHOLD",
    "DEFAULT_RUN_FAILED_SPIKE_WINDOW",
    "DEFAULT_SECRET_ROTATION_DEFERRED_THRESHOLD",
    "RunFailedSpikeAlertContext",
    "SecretRotationDeferredAlertContext",
    "count_recent_failures",
    "is_overdue",
]
