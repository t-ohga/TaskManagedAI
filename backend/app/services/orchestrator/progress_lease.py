from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.repositories.agent_run_event import append_event
from backend.app.services.orchestrator._shared import (
    ORCHESTRATOR_ROLE_ID,
    TERMINAL_STATUS_VALUES,
    ensure_tenant_context,
    lease_token_hash,
    utc_now,
)


@dataclass(frozen=True)
class ProgressRecordedResult:
    run_id: UUID
    progress_seq: int
    recorded_at: datetime


@dataclass(frozen=True)
class ProgressLeaseBlockedResult:
    run_id: UUID
    previous_progress_at: datetime | None
    lease_token_hash: str | None
    event: AgentRunEvent


class OrchestratorProgressLease:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_progress(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        now: datetime | None = None,
    ) -> ProgressRecordedResult | None:
        """Update last_progress_at and progress_seq for a non-terminal orchestrator."""

        await ensure_tenant_context(self._session, tenant_id)
        resolved_now = now or utc_now()
        result = await self._session.execute(
            sa.update(AgentRun)
            .where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == run_id,
                AgentRun.role_id == ORCHESTRATOR_ROLE_ID,
                AgentRun.status.not_in(TERMINAL_STATUS_VALUES),
            )
            .values(
                last_progress_at=resolved_now,
                progress_seq=AgentRun.progress_seq + 1,
                updated_at=resolved_now,
            )
            .returning(AgentRun.id, AgentRun.progress_seq)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return ProgressRecordedResult(
            run_id=row.id,
            progress_seq=int(row.progress_seq),
            recorded_at=resolved_now,
        )

    async def block_no_progress(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        actor_id: UUID,
        max_idle: timedelta = timedelta(minutes=30),
        now: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> ProgressLeaseBlockedResult | None:
        """Block a running orchestrator when no progress was recorded in time."""

        await ensure_tenant_context(self._session, tenant_id)
        if max_idle.total_seconds() <= 0:
            raise ValueError("max_idle must be positive.")

        resolved_now = now or utc_now()
        cutoff = resolved_now - max_idle
        result = await self._session.execute(
            sa.update(AgentRun)
            .where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == run_id,
                AgentRun.role_id == ORCHESTRATOR_ROLE_ID,
                AgentRun.status == "running",
                sa.func.coalesce(AgentRun.last_progress_at, AgentRun.created_at) <= cutoff,
            )
            .values(
                status="blocked",
                blocked_reason="runtime_blocked",
                error_code="progress_lease_violated",
                error_summary="orchestrator progress lease violated",
                updated_at=resolved_now,
            )
            .returning(
                AgentRun.id,
                AgentRun.last_progress_at,
                AgentRun.orchestrator_lease_token,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None

        token_hash = lease_token_hash(row.orchestrator_lease_token)
        event = await append_event(
            self._session,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="orchestrator_lease_expired",
            actor_id=actor_id,
            payload={
                "old_lease_hash": token_hash,
                "expired_at": resolved_now.isoformat(),
                "reason_code": "progress_lease_violated",
                "max_idle_seconds": int(max_idle.total_seconds()),
            },
            idempotency_key=idempotency_key or f"orchestrator-progress-expired:{run_id}",
        )
        return ProgressLeaseBlockedResult(
            run_id=row.id,
            previous_progress_at=row.last_progress_at,
            lease_token_hash=token_hash,
            event=event,
        )


__all__ = [
    "OrchestratorProgressLease",
    "ProgressLeaseBlockedResult",
    "ProgressRecordedResult",
]
