from __future__ import annotations

import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.domain.review_artifact import (
    REVIEW_ARTIFACT_ACTION_CLASSES,
    REVIEW_ARTIFACT_VERDICTS,
    ReviewArtifactActionClass,
    ReviewArtifactVerdict,
)

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class ReviewArtifactCreate(BaseModel):
    """Caller-facing review_artifacts payload.

    tenant_id and project_id are intentionally excluded. The service resolves
    those boundaries server-side from the current tenant/project context.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    parent_run_id: UUID
    requester_run_id: UUID
    reviewer_run_id: UUID
    review_target_artifact_id: UUID
    review_artifact_id: UUID
    action_class: ReviewArtifactActionClass
    target_artifact_hash: str = Field(..., min_length=64, max_length=64)
    policy_version: str = Field(..., min_length=1, max_length=128)
    provider_request_fingerprint_hash: str = Field(..., min_length=64, max_length=64)
    review_verdict: ReviewArtifactVerdict
    findings_count: int = Field(default=0, ge=0)

    @field_validator("action_class")
    @classmethod
    def _action_class_allowed(cls, value: str) -> str:
        if value not in REVIEW_ARTIFACT_ACTION_CLASSES:
            raise ValueError(
                "action_class must be one of "
                f"{sorted(REVIEW_ARTIFACT_ACTION_CLASSES)}"
            )
        return value

    @field_validator("review_verdict")
    @classmethod
    def _review_verdict_allowed(cls, value: str) -> str:
        if value not in REVIEW_ARTIFACT_VERDICTS:
            raise ValueError(
                f"review_verdict must be one of {sorted(REVIEW_ARTIFACT_VERDICTS)}"
            )
        return value

    @field_validator("target_artifact_hash", "provider_request_fingerprint_hash")
    @classmethod
    def _sha256_hex(cls, value: str) -> str:
        if _SHA256_HEX_RE.fullmatch(value) is None:
            raise ValueError("hash fields must be lowercase SHA-256 hex.")
        return value

    @field_validator("policy_version")
    @classmethod
    def _policy_version_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("policy_version must be non-empty.")
        return value

    @model_validator(mode="after")
    def _reviewer_must_differ(self) -> ReviewArtifactCreate:
        if self.reviewer_run_id == self.requester_run_id:
            raise ValueError("reviewer_run_id must differ from requester_run_id.")
        if self.review_artifact_id == self.review_target_artifact_id:
            raise ValueError("review_artifact_id must differ from review_target_artifact_id.")
        return self


__all__ = ["ReviewArtifactCreate"]
