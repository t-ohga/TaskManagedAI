from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.db.models.inter_agent_message import InterAgentReceiverKind
from backend.app.services.input_trust.payload_classifier import PayloadClassificationInput


class InterAgentPublishRequest(BaseModel):
    """Caller-facing inter-agent publish payload.

    tenant_id, project_id, sender_actor_id, and payload_data_class are
    intentionally absent. The service resolves those values from server-owned
    context and classifier output.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_run_id: UUID
    sender_run_id: UUID
    receiver_kind: InterAgentReceiverKind
    child_run_id: UUID | None = None
    receiver_ref: str | None = Field(default=None, max_length=128)
    payload: dict[str, Any]
    classification: PayloadClassificationInput = Field(
        default_factory=PayloadClassificationInput
    )
    schema_version: str = Field(default="inter-agent-message.v1", min_length=1, max_length=64)
    idempotency_key: str = Field(..., min_length=1, max_length=256)
    expires_at: datetime

    @field_validator("receiver_ref")
    @classmethod
    def _blank_receiver_ref_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("receiver_ref must be non-empty when provided.")
        return stripped

    @field_validator("expires_at")
    @classmethod
    def _expires_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def _receiver_target_shape(self) -> InterAgentPublishRequest:
        if self.receiver_kind == "agent_run":
            if self.child_run_id is None:
                raise ValueError("child_run_id is required for receiver_kind='agent_run'.")
            if self.receiver_ref is not None:
                raise ValueError("receiver_ref must be null for receiver_kind='agent_run'.")
        elif self.receiver_kind == "role":
            if self.child_run_id is not None:
                raise ValueError("child_run_id must be null for receiver_kind='role'.")
            if self.receiver_ref is None:
                raise ValueError("receiver_ref is required for receiver_kind='role'.")
        elif self.receiver_kind == "broadcast":
            if self.child_run_id is not None or self.receiver_ref is not None:
                raise ValueError(
                    "child_run_id and receiver_ref must be null for receiver_kind='broadcast'."
                )
        return self


class InterAgentConsumeRequest(BaseModel):
    """Caller-facing inter-agent consume request.

    tenant_id and project_id are excluded; the service receives those from
    server-owned execution context.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_run_id: UUID
    message_id: UUID
    consumer_run_id: UUID


__all__ = ["InterAgentConsumeRequest", "InterAgentPublishRequest"]
