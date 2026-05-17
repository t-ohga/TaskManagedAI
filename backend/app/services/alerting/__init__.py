"""Alerting service module (Sprint 11.5 batch 2、BL-0135).

4 alert kind を In-App Notification 経由で emit:
- approval_pending_overdue: approval が threshold (default 4h) 超過
- budget_exceeded: provider budget hard limit hit
- run_failed_spike: 5 分 window で N 件以上 run_failed
- secret_rotation_deferred: rotation deprecated が threshold (default 7 day) 超過

CRITICAL invariant trace:
- SecretBroker boundary: alert payload に raw secret を含めない、secret_ref のみ参照
- 5+ source enum integrity: AlertKind Literal + frozenset + EXPECTED + Pydantic
- AgentRun 16 状態: alert trigger 元として既存 enum 不変
"""

from __future__ import annotations

from backend.app.services.alerting.evaluator import (
    AlertEmittedSummary,
    AlertEvaluator,
    ApprovalPendingAlertContext,
    BudgetExceededAlertContext,
    RunFailedSpikeAlertContext,
    SecretRotationDeferredAlertContext,
)
from backend.app.services.alerting.kinds import (
    ALERT_KIND_VALUES,
    EXPECTED_ALERT_KINDS,
    AlertKind,
)

__all__ = [
    "ALERT_KIND_VALUES",
    "AlertEmittedSummary",
    "AlertEvaluator",
    "AlertKind",
    "ApprovalPendingAlertContext",
    "BudgetExceededAlertContext",
    "EXPECTED_ALERT_KINDS",
    "RunFailedSpikeAlertContext",
    "SecretRotationDeferredAlertContext",
]
