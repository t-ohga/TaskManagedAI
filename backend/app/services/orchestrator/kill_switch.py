from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.actor import Actor
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
class KillSwitchResult:
    run_id: UUID
    lease_token_hash: str | None
    killed_at: datetime
    event: AgentRunEvent


class OrchestratorKillSwitch:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def engage(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        actor_id: UUID,
        reason: str,
        now: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> KillSwitchResult | None:
        """Engage the orchestrator kill switch for a running run."""

        await ensure_tenant_context(self._session, tenant_id)
        if not reason.strip():
            raise ValueError("kill switch reason must be non-empty.")

        actor_type = await self._session.scalar(
            sa.select(Actor.actor_type).where(
                Actor.tenant_id == tenant_id,
                Actor.id == actor_id,
            )
        )
        if actor_type != "human":
            raise ValueError("kill switch actor_id must reference a human actor.")

        resolved_now = now or utc_now()
        result = await self._session.execute(
            sa.update(AgentRun)
            .where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == run_id,
                AgentRun.role_id == ORCHESTRATOR_ROLE_ID,
                AgentRun.status == "running",
            )
            .values(
                status="blocked",
                blocked_reason="runtime_blocked",
                orchestrator_kill_at=resolved_now,
                error_code="orchestrator_kill_engaged",
                error_summary="orchestrator kill switch engaged",
                updated_at=resolved_now,
            )
            .returning(AgentRun.id, AgentRun.orchestrator_lease_token)
        )
        row = result.one_or_none()
        if row is None:
            return None

        token_hash = lease_token_hash(row.orchestrator_lease_token)
        event = await append_event(
            self._session,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="orchestrator_kill_engaged",
            actor_id=actor_id,
            payload={
                "engaged_by_actor_id": str(actor_id),
                "lease_token_hash": token_hash,
                "engaged_at": resolved_now.isoformat(),
                "reason": reason,
            },
            idempotency_key=idempotency_key or f"orchestrator-kill:{run_id}",
        )
        return KillSwitchResult(
            run_id=row.id,
            lease_token_hash=token_hash,
            killed_at=resolved_now,
            event=event,
        )


__all__ = ["KillSwitchResult", "OrchestratorKillSwitch"]
