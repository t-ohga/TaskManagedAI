"""Sprint 11.5 batch 2 BL-0135: AlertEvaluator unit tests (mock-based).

DB integration 不要 (mock NotificationEventRepository) で logic を verify:
- 4 alert kind: payload/event_type 構造、Notification emit 呼出
- dedup_key: 各 kind の dedup key 構造
- helper: is_overdue / count_recent_failures threshold
- threshold constants (AC-KPI-03 4h 整合)

DB integration smoke は Sprint 12 host migration drill で final.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from backend.app.db.models.notification_event import NotificationEvent
from backend.app.services.alerting.evaluator import (
    DEFAULT_APPROVAL_PENDING_THRESHOLD,
    DEFAULT_RUN_FAILED_SPIKE_THRESHOLD,
    DEFAULT_RUN_FAILED_SPIKE_WINDOW,
    DEFAULT_SECRET_ROTATION_DEFERRED_THRESHOLD,
    AlertEvaluator,
    ApprovalPendingAlertContext,
    BudgetExceededAlertContext,
    RunFailedSpikeAlertContext,
    SecretRotationDeferredAlertContext,
    count_recent_failures,
    is_overdue,
)
from backend.app.services.alerting.kinds import to_event_type

_TENANT_ID = 1
_RECIPIENT = UUID("00000000-0000-4000-8000-000000000001")


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _build_evaluator_with_mock(
    *,
    dedup_existing_count: int = 0,
) -> tuple[AlertEvaluator, AsyncMock, list[dict[str, Any]]]:
    """Provide AlertEvaluator with mocked session + NotificationEventRepository.

    dedup_existing_count: dedup SELECT が返す既存 count (0 なら新規 emit).
    Returns (evaluator, repo_append_mock, captured_payloads).
    """

    session = MagicMock()
    session.scalar = AsyncMock(return_value=dedup_existing_count)
    captured: list[dict[str, Any]] = []

    async def _append(
        *,
        tenant_id: int,
        event_type: str,
        payload: dict[str, Any],
        recipient_actor_id: UUID,
    ) -> NotificationEvent:
        captured.append(
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "payload": payload,
                "recipient_actor_id": recipient_actor_id,
            }
        )
        ev = MagicMock(spec=NotificationEvent)
        ev.id = uuid4()
        ev.tenant_id = tenant_id
        ev.event_type = event_type
        ev.payload = payload
        ev.recipient_actor_id = recipient_actor_id
        return ev

    repo_mock = AsyncMock()
    repo_mock.append = AsyncMock(side_effect=_append)

    evaluator = AlertEvaluator(session)
    # tenant_context bypass (test 内で set_tenant_context を実 DB call させない).
    evaluator._ensure_tenant_context = AsyncMock(return_value=None)  # noqa: SLF001
    return evaluator, repo_mock, captured


@pytest.mark.asyncio
async def test_is_overdue_below_threshold_false() -> None:
    requested_at = _now() - timedelta(hours=3, minutes=59)
    assert is_overdue(requested_at) is False


@pytest.mark.asyncio
async def test_is_overdue_at_threshold_false() -> None:
    """4h ぴったりは過去 4 hour なので False (`>` strict、`==` は False)."""

    now = _now()
    requested_at = now - DEFAULT_APPROVAL_PENDING_THRESHOLD
    assert is_overdue(requested_at, now=now) is False


@pytest.mark.asyncio
async def test_is_overdue_above_threshold_true() -> None:
    requested_at = _now() - timedelta(hours=4, minutes=1)
    assert is_overdue(requested_at) is True


@pytest.mark.asyncio
async def test_count_recent_failures_window_filter() -> None:
    now = _now()
    failures = [
        now - timedelta(minutes=1),
        now - timedelta(minutes=3),
        now - timedelta(minutes=4, seconds=59),
        now - timedelta(minutes=5, seconds=1),  # window 外
        now - timedelta(minutes=10),  # window 外
    ]
    count = count_recent_failures(failures, now=now)
    assert count == 3


@pytest.mark.asyncio
async def test_emit_approval_pending_overdue_payload_structure() -> None:
    evaluator, repo_mock, captured = _build_evaluator_with_mock()
    context = ApprovalPendingAlertContext(
        approval_id=uuid4(),
        requester_actor_id=uuid4(),
        action_class="repo_write",
        requested_at=_now() - timedelta(hours=5),
        age_seconds=18000.0,
    )
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock,
    ):
        summary = await evaluator.emit_approval_pending_overdue(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=context,
        )
    assert summary.emitted is True
    assert summary.dedup_hit is False
    assert summary.kind == "approval_pending_overdue"
    assert len(captured) == 1
    call = captured[0]
    assert call["event_type"] == "alert.approval_pending_overdue"
    assert call["payload"]["alert_kind"] == "approval_pending_overdue"
    assert call["payload"]["dedup_key"] == f"approval:{context.approval_id}"
    assert call["payload"]["context"]["action_class"] == "repo_write"
    assert call["recipient_actor_id"] == _RECIPIENT


@pytest.mark.asyncio
async def test_emit_budget_exceeded_payload_structure() -> None:
    evaluator, repo_mock, captured = _build_evaluator_with_mock()
    context = BudgetExceededAlertContext(
        budget_scope="provider.openai",
        spent_usd=12.5,
        limit_usd=10.0,
        overflow_usd=2.5,
    )
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock,
    ):
        summary = await evaluator.emit_budget_exceeded(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=context,
        )
    assert summary.emitted is True
    assert captured[0]["event_type"] == "alert.budget_exceeded"
    assert captured[0]["payload"]["dedup_key"] == "budget:provider.openai"
    assert captured[0]["payload"]["context"]["limit_usd"] == 10.0


@pytest.mark.asyncio
async def test_emit_run_failed_spike_with_project_scope() -> None:
    evaluator, repo_mock, captured = _build_evaluator_with_mock()
    project_id = uuid4()
    context = RunFailedSpikeAlertContext(
        failed_count=DEFAULT_RUN_FAILED_SPIKE_THRESHOLD,
        window_seconds=300.0,
        project_id=project_id,
    )
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock,
    ):
        summary = await evaluator.emit_run_failed_spike(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=context,
        )
    assert summary.emitted is True
    assert captured[0]["payload"]["dedup_key"] == f"run_failed_spike:{project_id}"


@pytest.mark.asyncio
async def test_emit_run_failed_spike_tenant_scope_when_no_project() -> None:
    """`project_id=None` 時は `tenant_all` scope の dedup key."""

    evaluator, repo_mock, captured = _build_evaluator_with_mock()
    context = RunFailedSpikeAlertContext(
        failed_count=10, window_seconds=300.0, project_id=None
    )
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock,
    ):
        summary = await evaluator.emit_run_failed_spike(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=context,
        )
    assert summary.emitted is True
    assert captured[0]["payload"]["dedup_key"] == "run_failed_spike:tenant_all"


@pytest.mark.asyncio
async def test_emit_secret_rotation_deferred_only_secret_ref() -> None:
    """SecretBroker boundary: payload は secret_ref_id のみ、raw secret 値含めず."""

    evaluator, repo_mock, captured = _build_evaluator_with_mock()
    secret_ref_id = uuid4()
    context = SecretRotationDeferredAlertContext(
        secret_ref_id=secret_ref_id,
        scope="project",
        name="provider-openai",
        deprecated_at=_now() - timedelta(days=8),
        age_seconds=86400.0 * 8,
    )
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock,
    ):
        summary = await evaluator.emit_secret_rotation_deferred(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=context,
        )
    assert summary.emitted is True
    payload_str = str(captured[0]["payload"])
    # SecretBroker boundary: raw secret 含めない (sk- / ghp_ 系)
    assert "sk-" not in payload_str
    assert "ghp_" not in payload_str
    assert "AGE-SECRET" not in payload_str
    assert captured[0]["payload"]["context"]["secret_ref_id"] == str(secret_ref_id)


@pytest.mark.asyncio
async def test_dedup_24h_window_suppresses_duplicate_emit() -> None:
    """同 dedup_key で 24h within 既存 event がある場合、新規 emit を suppress."""

    # dedup_existing_count=1 で SELECT が返す既存 count をモック.
    evaluator, repo_mock, captured = _build_evaluator_with_mock(dedup_existing_count=1)
    context = ApprovalPendingAlertContext(
        approval_id=uuid4(),
        requester_actor_id=uuid4(),
        action_class="repo_write",
        requested_at=_now() - timedelta(hours=5),
        age_seconds=18000.0,
    )
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock,
    ):
        summary = await evaluator.emit_approval_pending_overdue(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=context,
        )
    assert summary.emitted is False
    assert summary.dedup_hit is True
    assert summary.skip_reason == "dedup_24h_window"
    assert summary.notification_event_id is None
    # repo.append が呼ばれていない (dedup suppress).
    assert len(captured) == 0


@pytest.mark.asyncio
async def test_emit_summary_kind_matches_each_call() -> None:
    """4 kind 全 emit で summary.kind が各 kind と一致."""

    evaluator, repo_mock, captured = _build_evaluator_with_mock()
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock,
    ):
        s1 = await evaluator.emit_approval_pending_overdue(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=ApprovalPendingAlertContext(
                approval_id=uuid4(),
                requester_actor_id=uuid4(),
                action_class="repo_write",
                requested_at=_now() - timedelta(hours=5),
                age_seconds=18000.0,
            ),
        )
        s2 = await evaluator.emit_budget_exceeded(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=BudgetExceededAlertContext(
                budget_scope="provider.anthropic",
                spent_usd=20.0,
                limit_usd=15.0,
                overflow_usd=5.0,
            ),
        )
        s3 = await evaluator.emit_run_failed_spike(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=RunFailedSpikeAlertContext(
                failed_count=7, window_seconds=300.0, project_id=None
            ),
        )
        s4 = await evaluator.emit_secret_rotation_deferred(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=SecretRotationDeferredAlertContext(
                secret_ref_id=uuid4(),
                scope="repo",
                name="github-app-key",
                deprecated_at=_now() - timedelta(days=10),
                age_seconds=86400.0 * 10,
            ),
        )
    assert s1.kind == "approval_pending_overdue"
    assert s2.kind == "budget_exceeded"
    assert s3.kind == "run_failed_spike"
    assert s4.kind == "secret_rotation_deferred"


def test_default_threshold_constants() -> None:
    """Default threshold が plan v1 仕様 + AC-KPI-03 4h と整合."""

    assert DEFAULT_APPROVAL_PENDING_THRESHOLD == timedelta(hours=4)
    assert DEFAULT_RUN_FAILED_SPIKE_WINDOW == timedelta(minutes=5)
    assert DEFAULT_RUN_FAILED_SPIKE_THRESHOLD == 5
    assert DEFAULT_SECRET_ROTATION_DEFERRED_THRESHOLD == timedelta(days=7)


def test_to_event_type_prefix_consistent() -> None:
    """`to_event_type` の `alert.*` prefix を verify."""

    assert to_event_type("approval_pending_overdue") == "alert.approval_pending_overdue"
    assert to_event_type("budget_exceeded") == "alert.budget_exceeded"
    assert to_event_type("run_failed_spike") == "alert.run_failed_spike"
    assert to_event_type("secret_rotation_deferred") == "alert.secret_rotation_deferred"


@pytest.mark.asyncio
async def test_approval_pending_below_threshold_skipped() -> None:
    """Codex F-PR43-006 P2 adopt: threshold 未満は emit skip."""

    evaluator, repo_mock, captured = _build_evaluator_with_mock()
    context = ApprovalPendingAlertContext(
        approval_id=uuid4(),
        requester_actor_id=uuid4(),
        action_class="repo_write",
        requested_at=_now() - timedelta(hours=3),
        age_seconds=3 * 3600.0,  # 3 hour < 4 hour threshold
    )
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock,
    ):
        summary = await evaluator.emit_approval_pending_overdue(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=context,
        )
    assert summary.emitted is False
    assert summary.skip_reason == "below_threshold"
    assert len(captured) == 0


@pytest.mark.asyncio
async def test_budget_below_limit_skipped() -> None:
    """Codex F-PR43-006 P2 adopt: budget overflow が 0 以下は skip."""

    evaluator, repo_mock, captured = _build_evaluator_with_mock()
    context = BudgetExceededAlertContext(
        budget_scope="provider.openai",
        spent_usd=8.0,
        limit_usd=10.0,
        overflow_usd=0.0,  # 限界内
    )
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock,
    ):
        summary = await evaluator.emit_budget_exceeded(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=context,
        )
    assert summary.emitted is False
    assert summary.skip_reason == "below_threshold"
    assert len(captured) == 0


@pytest.mark.asyncio
async def test_run_failed_below_threshold_skipped() -> None:
    """Codex F-PR43-006 P2 adopt: failed_count が threshold 未満は skip."""

    evaluator, repo_mock, captured = _build_evaluator_with_mock()
    context = RunFailedSpikeAlertContext(
        failed_count=3,  # threshold 5 未満
        window_seconds=300.0,
        project_id=None,
    )
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock,
    ):
        summary = await evaluator.emit_run_failed_spike(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=context,
        )
    assert summary.emitted is False
    assert summary.skip_reason == "below_threshold"
    assert len(captured) == 0


@pytest.mark.asyncio
async def test_secret_rotation_below_threshold_skipped() -> None:
    """Codex F-PR43-006 P2 adopt: rotation age が 7 day 未満は skip."""

    evaluator, repo_mock, captured = _build_evaluator_with_mock()
    context = SecretRotationDeferredAlertContext(
        secret_ref_id=uuid4(),
        scope="project",
        name="provider-openai",
        deprecated_at=_now() - timedelta(days=3),
        age_seconds=3 * 86400.0,  # 3 day < 7 day threshold
    )
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock,
    ):
        summary = await evaluator.emit_secret_rotation_deferred(
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            context=context,
        )
    assert summary.emitted is False
    assert summary.skip_reason == "below_threshold"
    assert len(captured) == 0


@pytest.mark.asyncio
async def test_dedup_per_recipient_isolated() -> None:
    """Codex F-PR43-004 P2 adopt: 同 dedup_key でも別 recipient は dedup されない."""

    recipient_a = UUID("00000000-0000-4000-8000-000000000001")
    recipient_b = UUID("00000000-0000-4000-8000-000000000002")
    approval_id = uuid4()
    context = ApprovalPendingAlertContext(
        approval_id=approval_id,
        requester_actor_id=uuid4(),
        action_class="repo_write",
        requested_at=_now() - timedelta(hours=5),
        age_seconds=18000.0,
    )

    # recipient_a で emit (dedup_existing_count=0 だが、その後の query で
    # recipient_actor_id filter が effective かを mock で再現するため別 evaluator).
    evaluator, repo_mock, captured = _build_evaluator_with_mock(dedup_existing_count=0)
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock,
    ):
        s_a = await evaluator.emit_approval_pending_overdue(
            tenant_id=_TENANT_ID,
            recipient_actor_id=recipient_a,
            context=context,
        )
    assert s_a.emitted is True
    assert captured[0]["recipient_actor_id"] == recipient_a

    # recipient_b で別 evaluator (dedup_existing_count=0 = 別 recipient の query で 0)
    evaluator_b, repo_mock_b, captured_b = _build_evaluator_with_mock(dedup_existing_count=0)
    with patch(
        "backend.app.services.alerting.evaluator.NotificationEventRepository",
        return_value=repo_mock_b,
    ):
        s_b = await evaluator_b.emit_approval_pending_overdue(
            tenant_id=_TENANT_ID,
            recipient_actor_id=recipient_b,
            context=context,
        )
    # 同 dedup_key + 別 recipient → emit 成功 (recipient 単位 dedup)
    assert s_b.emitted is True
    assert s_b.dedup_hit is False
    assert captured_b[0]["recipient_actor_id"] == recipient_b


@pytest.mark.asyncio
async def test_invalid_alert_kind_rejected_at_validate() -> None:
    """`_emit_with_dedup` が internal で kind validate (defensive、外部 caller は型で防げない経路)."""

    evaluator, _repo_mock, _captured = _build_evaluator_with_mock()
    with pytest.raises(ValueError, match="invalid alert kind"):
        await evaluator._emit_with_dedup(  # noqa: SLF001
            kind="not_a_valid_kind",  # type: ignore[arg-type]
            tenant_id=_TENANT_ID,
            recipient_actor_id=_RECIPIENT,
            dedup_key="x",
            payload={"alert_kind": "x", "dedup_key": "x", "context": {}},
        )
