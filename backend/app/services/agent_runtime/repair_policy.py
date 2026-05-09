from __future__ import annotations

from backend.app.db.models.agent_run import AgentRun
from backend.app.domain.artifact.plan import MAX_REPAIR_RETRIES


def should_repair(run: AgentRun, retry_count: int) -> bool:
    _ = run
    if retry_count < 0:
        raise ValueError("retry_count must be zero or greater.")
    return retry_count < MAX_REPAIR_RETRIES


__all__ = ["MAX_REPAIR_RETRIES", "should_repair"]

