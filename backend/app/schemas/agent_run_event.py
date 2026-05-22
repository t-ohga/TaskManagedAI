from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.agent_runtime.event_type import AgentRunEventType


class AgentRunEventAppend(BaseModel):
    """Pydantic source for AgentRunEvent append payload validation.

    API routes do not accept arbitrary AgentRunEvent creation in P0, but keeping
    this schema aligned with the domain Literal prevents event_type drift when a
    future read/write endpoint is added.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    event_type: AgentRunEventType
    event_payload: dict[str, Any] = Field(default_factory=dict)
    actor_id: UUID
    idempotency_key: str | None = None


__all__ = ["AgentRunEventAppend"]
