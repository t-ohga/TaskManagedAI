from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.artifact import Artifact
from backend.app.domain.review_artifact import (
    REVIEW_ARTIFACT_ACTION_CLASSES,
    ReviewArtifactActionClass,
)
from backend.app.schemas.review_artifact import ReviewArtifactCreate
from backend.app.services.orchestrator._shared import (
    ORCHESTRATOR_ROLE_ID,
    ensure_tenant_context,
)

REVIEWER_ROLE_ID = "reviewer"
REVIEWER_ROLE_SCOPE = "global"
_POLICY_INPUT_KEY = "policy_input"


class ReviewArtifactValidationError(ValueError):
    """Raised when a review_artifact candidate violates SP-014 invariants."""


@dataclass(frozen=True)
class ReviewArtifactValidationResult:
    action_class: ReviewArtifactActionClass
    target_artifact_hash: str
    policy_version: str
    provider_request_fingerprint_hash: str


async def validate_review_artifact_for_action_class(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    candidate: ReviewArtifactCreate,
) -> ReviewArtifactValidationResult:
    """Validate the four-layer review_artifacts service boundary.

    This function does not insert the row. It verifies the server-owned run and
    artifact boundaries before the caller persists a ReviewArtifact model.
    """

    await ensure_tenant_context(session, tenant_id)

    if candidate.action_class not in REVIEW_ARTIFACT_ACTION_CLASSES:
        raise ReviewArtifactValidationError("action_class is not review-artifact eligible.")

    runs = await _load_runs(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        run_ids={
            candidate.parent_run_id,
            candidate.requester_run_id,
            candidate.reviewer_run_id,
        },
    )
    parent_run = _require_run(runs, candidate.parent_run_id, "parent_run_id")
    requester_run = _require_run(runs, candidate.requester_run_id, "requester_run_id")
    reviewer_run = _require_run(runs, candidate.reviewer_run_id, "reviewer_run_id")

    if candidate.requester_run_id == candidate.reviewer_run_id:
        raise ReviewArtifactValidationError("reviewer_run_id must differ from requester_run_id.")
    if candidate.review_artifact_id == candidate.review_target_artifact_id:
        raise ReviewArtifactValidationError(
            "review_artifact_id must differ from review_target_artifact_id."
        )
    if parent_run.role_id != ORCHESTRATOR_ROLE_ID:
        raise ReviewArtifactValidationError("parent_run_id must be an orchestrator run.")
    if requester_run.parent_run_id != candidate.parent_run_id:
        raise ReviewArtifactValidationError("requester_run_id must be under parent_run_id.")
    if reviewer_run.parent_run_id != candidate.parent_run_id:
        raise ReviewArtifactValidationError("reviewer_run_id must be under parent_run_id.")
    if (
        reviewer_run.role_id != REVIEWER_ROLE_ID
        or reviewer_run.role_scope != REVIEWER_ROLE_SCOPE
    ):
        raise ReviewArtifactValidationError(
            "reviewer_run_id must resolve to role_id='reviewer' and role_scope='global'."
        )

    artifacts = await _load_artifacts(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        artifact_ids={
            candidate.review_target_artifact_id,
            candidate.review_artifact_id,
        },
    )
    target_artifact = _require_artifact(
        artifacts,
        candidate.review_target_artifact_id,
        "review_target_artifact_id",
    )
    review_artifact = _require_artifact(
        artifacts,
        candidate.review_artifact_id,
        "review_artifact_id",
    )

    if target_artifact.run_id != candidate.requester_run_id:
        raise ReviewArtifactValidationError(
            "review_target_artifact_id must belong to requester_run_id."
        )
    if review_artifact.run_id != candidate.reviewer_run_id:
        raise ReviewArtifactValidationError(
            "review_artifact_id must belong to reviewer_run_id."
        )
    if review_artifact.trust_level != "validated_artifact":
        raise ReviewArtifactValidationError(
            "review_artifact_id must reference a validated_artifact."
        )
    if target_artifact.content_hash != candidate.target_artifact_hash:
        raise ReviewArtifactValidationError(
            "target_artifact_hash must match review_target_artifact_id content_hash."
        )

    _assert_policy_binding(
        target_artifact.content_jsonb,
        action_class=candidate.action_class,
        policy_version=candidate.policy_version,
        provider_request_fingerprint_hash=candidate.provider_request_fingerprint_hash,
    )
    _assert_review_artifact_payload(
        review_artifact.content_jsonb,
        review_verdict=candidate.review_verdict,
        findings_count=candidate.findings_count,
    )

    return ReviewArtifactValidationResult(
        action_class=candidate.action_class,
        target_artifact_hash=candidate.target_artifact_hash,
        policy_version=candidate.policy_version,
        provider_request_fingerprint_hash=candidate.provider_request_fingerprint_hash,
    )


async def _load_runs(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    run_ids: set[UUID],
) -> dict[UUID, AgentRun]:
    result = await session.execute(
        sa.select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.project_id == project_id,
            AgentRun.id.in_(run_ids),
        )
    )
    return {run.id: run for run in result.scalars()}


def _require_run(
    runs: dict[UUID, AgentRun],
    run_id: UUID,
    label: str,
) -> AgentRun:
    run = runs.get(run_id)
    if run is None:
        raise ReviewArtifactValidationError(f"{label} not found in tenant/project boundary.")
    return run


async def _load_artifacts(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    artifact_ids: set[UUID],
) -> dict[UUID, Artifact]:
    result = await session.execute(
        sa.select(Artifact).where(
            Artifact.tenant_id == tenant_id,
            Artifact.project_id == project_id,
            Artifact.id.in_(artifact_ids),
        )
    )
    return {artifact.id: artifact for artifact in result.scalars()}


def _require_artifact(
    artifacts: dict[UUID, Artifact],
    artifact_id: UUID,
    label: str,
) -> Artifact:
    artifact = artifacts.get(artifact_id)
    if artifact is None:
        raise ReviewArtifactValidationError(
            f"{label} not found in tenant/project boundary."
        )
    return artifact


def _assert_policy_binding(
    payload: dict[str, object],
    *,
    action_class: str,
    policy_version: str,
    provider_request_fingerprint_hash: str,
) -> None:
    payload_action_class = _lookup_policy_input(payload, "action_class")
    if payload_action_class != action_class:
        raise ReviewArtifactValidationError(
            "action_class must match the review target policy binding."
        )

    payload_policy_version = _lookup_policy_input(payload, "policy_version")
    if payload_policy_version != policy_version:
        raise ReviewArtifactValidationError(
            "policy_version must match the review target policy binding."
        )

    payload_provider_hash = _lookup_policy_input(
        payload,
        "provider_request_fingerprint_hash",
    )
    if payload_provider_hash != provider_request_fingerprint_hash:
        raise ReviewArtifactValidationError(
            "provider_request_fingerprint_hash must match the review target policy binding."
        )


def _lookup_policy_input(payload: dict[str, object], key: str) -> object:
    policy_input = payload.get(_POLICY_INPUT_KEY)
    if isinstance(policy_input, dict):
        return policy_input.get(key)
    return None


def _assert_review_artifact_payload(
    payload: dict[str, object],
    *,
    review_verdict: str,
    findings_count: int,
) -> None:
    if payload.get("verdict") != review_verdict:
        raise ReviewArtifactValidationError(
            "review_verdict must match the reviewer artifact payload."
        )

    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise ReviewArtifactValidationError(
            "review artifact payload findings must be a list."
        )
    if len(findings) != findings_count:
        raise ReviewArtifactValidationError(
            "findings_count must match the reviewer artifact payload."
        )


__all__ = [
    "REVIEWER_ROLE_ID",
    "REVIEWER_ROLE_SCOPE",
    "ReviewArtifactValidationError",
    "ReviewArtifactValidationResult",
    "validate_review_artifact_for_action_class",
]
