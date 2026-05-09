from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.domain.agent_runtime.event_type import AgentRunEventType
from backend.app.domain.agent_runtime.status import (
    ALL_BLOCKED_REASONS,
    AgentRunStatus,
    BlockedReason,
    TERMINAL_STATES,
)
from backend.app.repositories.agent_run_event import append_event
from backend.app.services.agent_runtime.state_machine import (
    BLOCKED_EVENT_TYPE_REASON_MAPPING,
    validate_event_type_for_transition,
    validate_transition,
)


class AgentRunEventLogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def transition_with_event(
        self,
        *,
        run: AgentRun,
        to_state: AgentRunStatus,
        event_type: AgentRunEventType,
        payload: dict[str, Any],
        actor_id: UUID,
        blocked_reason: BlockedReason | None = None,
        tenant_id: int | None = None,
        idempotency_key: str | None = None,
        expected_previous_seq_no: int | None = None,
    ) -> AgentRunEvent:
        """status 遷移 + event append を同一 transaction で実行する。

        Caller が async with session.begin(): で wrap している前提で、status update
        と event append は同じ SQLAlchemy transaction に参加する。ここでは commit
        しない。

        Raises:
            ValueError: transition / event_type / blocked_reason が許可外
            IntegrityError: DB CHECK / UNIQUE violation
        """

        resolved_tenant_id = run.tenant_id if tenant_id is None else tenant_id
        await self._ensure_tenant_context(resolved_tenant_id)

        if run.tenant_id != resolved_tenant_id:
            raise ValueError("AgentRun tenant_id must match transition tenant_id.")

        from_state = run.status
        validate_transition(from_state, to_state)
        validate_event_type_for_transition(from_state, to_state, event_type)

        if to_state == "blocked":
            if blocked_reason is None:
                raise ValueError("blocked_reason required when transitioning to 'blocked'")
            if blocked_reason not in ALL_BLOCKED_REASONS:
                raise ValueError(f"unknown blocked_reason: {blocked_reason!r}")
            expected_reason = BLOCKED_EVENT_TYPE_REASON_MAPPING.get(event_type)
            if expected_reason is not None and blocked_reason != expected_reason:
                raise ValueError(
                    f"event_type {event_type!r} requires blocked_reason "
                    f"{expected_reason!r}, got {blocked_reason!r}"
                )
        elif blocked_reason is not None:
            raise ValueError(
                f"blocked_reason must be None when transitioning to {to_state!r}"
            )

        now = datetime.now(tz=UTC)
        values: dict[str, Any] = {
            "status": to_state,
            "blocked_reason": blocked_reason,
            "updated_at": now,
        }
        if to_state in TERMINAL_STATES:
            values["completed_at"] = now

        result = await self.session.execute(
            sa.update(AgentRun)
            .where(
                AgentRun.tenant_id == resolved_tenant_id,
                AgentRun.id == run.id,
                AgentRun.status == from_state,
            )
            .values(**values)
            .returning(AgentRun.id)
        )
        updated_run_id = result.scalar_one_or_none()
        if updated_run_id is None:
            raise ValueError(
                f"AgentRun {run.id} could not transition from {from_state!r} "
                f"to {to_state!r}: current status changed concurrently."
            )

        event = await append_event(
            self.session,
            tenant_id=resolved_tenant_id,
            run_id=run.id,
            event_type=event_type,
            actor_id=actor_id,
            payload=payload,
            idempotency_key=idempotency_key,
            expected_previous_seq_no=expected_previous_seq_no,
        )

        await self.session.refresh(run)
        return event

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")
        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
        await assert_tenant_context(self.session, tenant_id)


async def transition_with_event(
    session: AsyncSession,
    *,
    run: AgentRun,
    to_state: AgentRunStatus,
    event_type: AgentRunEventType,
    payload: dict[str, Any],
    actor_id: UUID,
    blocked_reason: BlockedReason | None = None,
    tenant_id: int | None = None,
    idempotency_key: str | None = None,
    expected_previous_seq_no: int | None = None,
) -> AgentRunEvent:
    return await AgentRunEventLogService(session).transition_with_event(
        run=run,
        to_state=to_state,
        event_type=event_type,
        payload=payload,
        actor_id=actor_id,
        blocked_reason=blocked_reason,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        expected_previous_seq_no=expected_previous_seq_no,
    )


__all__ = ["AgentRunEventLogService", "transition_with_event"]

