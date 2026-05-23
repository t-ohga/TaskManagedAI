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
class LeaseRenewalResult:
    run_id: UUID
    new_lease_token: UUID
    new_lease_token_hash: str
    expires_at: datetime
    event: AgentRunEvent


@dataclass(frozen=True)
class LeaseExpiredResult:
    run_id: UUID
    expired_lease_token_hash: str | None
    event: AgentRunEvent


class OrchestratorLeaseManager:
    """Atomic lease operations for SP-014 orchestrator runs.

    The caller owns transaction boundaries. Each method performs its AgentRun
    mutation and AgentRunEvent append on the same AsyncSession transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def renew_lease(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        actor_id: UUID,
        current_lease_token: UUID,
        ttl: timedelta = timedelta(seconds=60),
        now: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> LeaseRenewalResult | None:
        """Renew an active orchestrator lease with one conditional UPDATE.

        Returns None when the predicate fails: wrong token, expired lease,
        non-running run, tenant mismatch, or non-orchestrator role.
        """

        await ensure_tenant_context(self._session, tenant_id)
        resolved_now = now or utc_now()
        if ttl.total_seconds() <= 0:
            raise ValueError("lease ttl must be positive.")

        new_token = uuid4()
        expires_at = resolved_now + ttl
        new_hash = lease_token_hash(new_token)
        if new_hash is None:
            raise RuntimeError("lease_token_hash unexpectedly returned None for UUID.")

        result = await self._session.execute(
            sa.update(AgentRun)
            .where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == run_id,
                AgentRun.role_id == ORCHESTRATOR_ROLE_ID,
                AgentRun.orchestrator_lease_token == current_lease_token,
                AgentRun.orchestrator_lease_expires_at > resolved_now,
                AgentRun.status == "running",
            )
            .values(
                orchestrator_lease_token=new_token,
                orchestrator_lease_expires_at=expires_at,
                lease_renewed_at=resolved_now,
                updated_at=resolved_now,
            )
            .returning(AgentRun.id)
        )
        updated_run_id = result.scalar_one_or_none()
        if updated_run_id is None:
            return None

        old_hash = lease_token_hash(current_lease_token)
        event = await append_event(
            self._session,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="orchestrator_lease_renewed",
            actor_id=actor_id,
            payload={
                "previous_lease_token_hash": old_hash,
                "lease_token_hash": new_hash,
                "renewed_at": resolved_now.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
            idempotency_key=(
                idempotency_key or f"orchestrator-lease-renew:{run_id}:{new_hash}"
            ),
        )
        return LeaseRenewalResult(
            run_id=run_id,
            new_lease_token=new_token,
            new_lease_token_hash=new_hash,
            expires_at=expires_at,
            event=event,
        )

    async def expire_stale_lease(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        actor_id: UUID,
        now: datetime | None = None,
        reason_code: str = "lease_expired_no_secret_access",
        idempotency_key: str | None = None,
    ) -> LeaseExpiredResult | None:
        """Block a running orchestrator when its lease is expired."""

        await ensure_tenant_context(self._session, tenant_id)
        resolved_now = now or utc_now()
        result = await self._session.execute(
            sa.update(AgentRun)
            .where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == run_id,
                AgentRun.role_id == ORCHESTRATOR_ROLE_ID,
                AgentRun.status == "running",
                AgentRun.orchestrator_lease_expires_at <= resolved_now,
            )
            .values(
                status="blocked",
                blocked_reason="runtime_blocked",
                error_code=reason_code,
                error_summary="orchestrator lease expired",
                updated_at=resolved_now,
            )
            .returning(AgentRun.id, AgentRun.orchestrator_lease_token)
        )
        row = result.one_or_none()
        if row is None:
            return None

        expired_hash = lease_token_hash(row.orchestrator_lease_token)
        event = await append_event(
            self._session,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="orchestrator_lease_expired",
            actor_id=actor_id,
            payload={
                "old_lease_hash": expired_hash,
                "expired_at": resolved_now.isoformat(),
                "reason_code": reason_code,
            },
            idempotency_key=(
                idempotency_key or f"orchestrator-lease-expired:{run_id}:{reason_code}"
            ),
        )
        return LeaseExpiredResult(
            run_id=row.id,
            expired_lease_token_hash=expired_hash,
            event=event,
        )


__all__ = [
    "LeaseExpiredResult",
    "LeaseRenewalResult",
    "OrchestratorLeaseManager",
]
