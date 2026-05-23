from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.repositories.agent_run_event import append_event
from backend.app.services.orchestrator._shared import (
    ORCHESTRATOR_ROLE_ID,
    ensure_tenant_context,
)


@dataclass(frozen=True)
class DispatchRecordedResult:
    parent_run_id: UUID
    child_run_id: UUID
    event: AgentRunEvent


class OrchestratorDispatcher:
    """Records local child dispatch events.

    Child AgentRun creation remains owned by the caller for batch 0a. This
    service only records the server-owned dispatch trace after a child run id
    already exists.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_local_dispatch(
        self,
        *,
        tenant_id: int,
        parent_run_id: UUID,
        child_run_id: UUID,
        actor_id: UUID,
        dispatch_reason: str,
        recommended_provider: str,
        idempotency_key: str | None = None,
    ) -> DispatchRecordedResult:
        await ensure_tenant_context(self._session, tenant_id)
        if not dispatch_reason.strip():
            raise ValueError("dispatch_reason must be non-empty.")
        if not recommended_provider.strip():
            raise ValueError("recommended_provider must be non-empty.")

        parent_exists = await self._session.scalar(
            sa.select(AgentRun.id).where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == parent_run_id,
                AgentRun.role_id == ORCHESTRATOR_ROLE_ID,
                AgentRun.status == "running",
            )
        )
        if parent_exists is None:
            raise ValueError("parent_run_id must reference a running orchestrator run.")

        child = await self._session.execute(
            sa.select(AgentRun.id, AgentRun.role_id, AgentRun.role_scope).where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == child_run_id,
                AgentRun.parent_run_id == parent_run_id,
            )
        )
        child_row = child.one_or_none()
        if child_row is None:
            raise ValueError("child_run_id must reference a child of parent_run_id.")
        if child_row.role_id is None or child_row.role_scope is None:
            raise ValueError("child AgentRun must have server-resolved role_id and role_scope.")

        event = await append_event(
            self._session,
            tenant_id=tenant_id,
            run_id=parent_run_id,
            event_type="orchestrator_dispatched",
            actor_id=actor_id,
            payload={
                "child_run_id": str(child_run_id),
                "role_id": child_row.role_id,
                "role_scope": child_row.role_scope,
                "dispatch_reason": dispatch_reason,
                "recommended_provider": recommended_provider,
            },
            idempotency_key=idempotency_key
            or f"orchestrator-dispatched:{parent_run_id}:{child_run_id}",
        )
        return DispatchRecordedResult(
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            event=event,
        )


__all__ = ["DispatchRecordedResult", "OrchestratorDispatcher"]
