from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services.orchestrator.dispatcher import OrchestratorDispatcher
from backend.app.services.orchestrator.failover import OrchestratorFailover
from backend.app.services.orchestrator.kill_switch import OrchestratorKillSwitch
from backend.app.services.orchestrator.lease_manager import OrchestratorLeaseManager
from backend.app.services.orchestrator.progress_lease import OrchestratorProgressLease


class OrchestratorService:
    """Facade for SP-014 batch 0a orchestrator primitives."""

    def __init__(self, session: AsyncSession) -> None:
        self.lease_manager = OrchestratorLeaseManager(session)
        self.failover = OrchestratorFailover(session)
        self.kill_switch = OrchestratorKillSwitch(session)
        self.progress_lease = OrchestratorProgressLease(session)
        self.dispatcher = OrchestratorDispatcher(session)


__all__ = ["OrchestratorService"]
