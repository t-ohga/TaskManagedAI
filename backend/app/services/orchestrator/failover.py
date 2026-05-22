from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.repositories.agent_run_event import append_event
from backend.app.services.orchestrator._shared import (
    ORCHESTRATOR_ROLE_ID,
    ensure_tenant_context,
    lease_token_hash,
    utc_now,
)


@dataclass(frozen=True)
class FailoverResult:
    expired_run_id: UUID
    new_orchestrator_run_id: UUID
    new_lease_token: UUID
    new_lease_token_hash: str
    old_lease_token_hash: str | None
    lease_expired_event: AgentRunEvent
    failover_event: AgentRunEvent


class OrchestratorFailover:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def trigger_existing_standby(
        self,
        *,
        tenant_id: int,
        expired_run_id: UUID,
        standby_run_id: UUID,
        actor_id: UUID,
        ttl: timedelta = timedelta(seconds=60),
        now: datetime | None = None,
        reason_code: str = "lease_expired_no_secret_access",
        idempotency_key: str | None = None,
    ) -> FailoverResult | None:
        """Promote a queued standby orchestrator after an expired lease.

        The service does not create the standby row. Dispatch/queue ownership
        stays outside this primitive; this method atomically validates the old
        expired orchestrator, promotes the standby, blocks the expired run, and
        appends the two run-scoped events in one caller-owned transaction.
        """

        await ensure_tenant_context(self._session, tenant_id)
        if expired_run_id == standby_run_id:
            raise ValueError("expired_run_id and standby_run_id must differ.")
        if ttl.total_seconds() <= 0:
            raise ValueError("failover lease ttl must be positive.")
        if not reason_code.strip():
            raise ValueError("reason_code must be non-empty.")

        resolved_now = now or utc_now()
        expired = await self._session.execute(
            sa.select(
                AgentRun.id,
                AgentRun.project_id,
                AgentRun.orchestrator_lease_token,
            )
            .where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == expired_run_id,
                AgentRun.role_id == ORCHESTRATOR_ROLE_ID,
                AgentRun.status == "running",
                AgentRun.orchestrator_lease_expires_at <= resolved_now,
            )
            .with_for_update()
        )
        expired_row = expired.one_or_none()
        if expired_row is None:
            return None

        new_token = uuid4()
        new_expires_at = resolved_now + ttl
        new_hash = lease_token_hash(new_token)
        if new_hash is None:
            raise RuntimeError("lease_token_hash unexpectedly returned None for UUID.")

        promoted = await self._session.execute(
            sa.update(AgentRun)
            .where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == standby_run_id,
                AgentRun.project_id == expired_row.project_id,
                AgentRun.role_id == ORCHESTRATOR_ROLE_ID,
                AgentRun.status == "queued",
            )
            .values(
                status="running",
                orchestrator_lease_token=new_token,
                orchestrator_lease_expires_at=new_expires_at,
                lease_renewed_at=resolved_now,
                last_progress_at=resolved_now,
                updated_at=resolved_now,
            )
            .returning(AgentRun.id)
        )
        promoted_run_id = promoted.scalar_one_or_none()
        if promoted_run_id is None:
            return None

        blocked = await self._session.execute(
            sa.update(AgentRun)
            .where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == expired_run_id,
                AgentRun.status == "running",
            )
            .values(
                status="blocked",
                blocked_reason="runtime_blocked",
                error_code=reason_code,
                error_summary="orchestrator failover triggered after expired lease",
                updated_at=resolved_now,
            )
            .returning(AgentRun.id)
        )
        blocked_run_id = blocked.scalar_one_or_none()
        if blocked_run_id is None:
            raise ValueError("expired orchestrator status changed during failover.")

        old_hash = lease_token_hash(expired_row.orchestrator_lease_token)
        lease_expired_event = await append_event(
            self._session,
            tenant_id=tenant_id,
            run_id=expired_run_id,
            event_type="orchestrator_lease_expired",
            actor_id=actor_id,
            payload={
                "old_lease_hash": old_hash,
                "expired_at": resolved_now.isoformat(),
                "reason_code": reason_code,
            },
            idempotency_key=(
                idempotency_key or f"orchestrator-failover:{expired_run_id}:{standby_run_id}"
            )
            + ":lease-expired",
        )
        failover_event = await append_event(
            self._session,
            tenant_id=tenant_id,
            run_id=expired_run_id,
            event_type="orchestrator_failover_triggered",
            actor_id=actor_id,
            payload={
                "old_lease_hash": old_hash,
                "new_orchestrator_run_id": str(promoted_run_id),
                "new_lease_hash": new_hash,
                "reason_code": reason_code,
                "triggered_at": resolved_now.isoformat(),
            },
            idempotency_key=(
                idempotency_key or f"orchestrator-failover:{expired_run_id}:{standby_run_id}"
            )
            + ":triggered",
        )
        return FailoverResult(
            expired_run_id=expired_run_id,
            new_orchestrator_run_id=promoted_run_id,
            new_lease_token=new_token,
            new_lease_token_hash=new_hash,
            old_lease_token_hash=old_hash,
            lease_expired_event=lease_expired_event,
            failover_event=failover_event,
        )


__all__ = ["FailoverResult", "OrchestratorFailover"]
