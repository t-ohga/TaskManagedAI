from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ApiCapabilityAction = Literal[
    "task_list",
    "task_show",
    "task_create",
    "task_write",
    "approval_list",
    "approval_decide",
    "repo_status",
    "repo_push",
    "pr_open",
    "run_show",
    "run_cancel",
    "secret_resolve",
    "provider_call",
]
ApiCapabilityAuthMethod = Literal["keyring", "sops", "env", "plain"]

_SHA256_HEX_PATTERN = r"^[a-f0-9]{64}$"


class CliTokenIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID | None = None
    device_id: str | None = Field(default=None, min_length=1, max_length=128)
    allowed_actions: list[ApiCapabilityAction] = Field(min_length=1, max_length=13)
    scope_constraint: dict[str, Any] = Field(default_factory=dict)
    auth_method: ApiCapabilityAuthMethod
    auth_context_hash: str = Field(pattern=_SHA256_HEX_PATTERN)
    request_binding_hash: str = Field(pattern=_SHA256_HEX_PATTERN)
    ttl_minutes: int = Field(default=5, ge=5, le=30)

    @field_validator("allowed_actions")
    @classmethod
    def _allowed_actions_are_unique(
        cls,
        value: list[ApiCapabilityAction],
    ) -> list[ApiCapabilityAction]:
        if len(set(value)) != len(value):
            raise ValueError("allowed_actions must not contain duplicates.")
        return value


class CliTokenRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_token: str = Field(min_length=32, max_length=512)
    ttl_minutes: int = Field(default=5, ge=5, le=30)


class CliTokenRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_token: str = Field(min_length=32, max_length=512)


class CliTokenIssueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["issued"]
    operation_token: str
    token_id: UUID
    principal_id: UUID
    expires_at: datetime
    audience: Literal["taskmanagedai-api"]
    allowed_actions: list[ApiCapabilityAction]


class CliTokenRevokeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["revoked"]
    token_id: UUID
    revoked_at: datetime


__all__ = [
    "ApiCapabilityAction",
    "ApiCapabilityAuthMethod",
    "CliTokenIssueRequest",
    "CliTokenIssueResponse",
    "CliTokenRefreshRequest",
    "CliTokenRevokeRequest",
    "CliTokenRevokeResponse",
]
