from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.actor import Actor
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.models.artifact import Artifact
from backend.app.db.models.inter_agent_message import InterAgentMessage
from backend.app.domain.artifact.data_class import PayloadDataClass
from backend.app.repositories.artifact import ArtifactRepository
from backend.app.schemas.inter_agent import InterAgentPublishRequest
from backend.app.services.input_trust.payload_classifier import classify_payload_data_class
from backend.app.services.inter_agent.event_writer import InterAgentEventWriter
from backend.app.services.inter_agent.sanitizer import (
    InterAgentPayloadRejected,
    SanitizedInterAgentPayload,
    sanitize_inter_agent_payload,
)
from backend.app.services.orchestrator._shared import ensure_tenant_context


class InterAgentPublishError(ValueError):
    """Raised when an inter-agent message publish request is invalid."""


TrustedInterAgentActionClass = Literal[
    "task_write",
    "repo_write",
    "pr_open",
    "secret_access",
    "provider_call",
]
TRUSTED_INTER_AGENT_ACTION_CLASSES: frozenset[str] = frozenset(
    {"task_write", "repo_write", "pr_open", "secret_access", "provider_call"}
)


@dataclass(frozen=True)
class TrustedInstructionGrant:
    approval_request_id: UUID
    source_artifact_id: UUID
    artifact_hash: str
    policy_version: str
    provider_request_fingerprint: str
    action_class: TrustedInterAgentActionClass


@dataclass(frozen=True)
class InterAgentPublishResult:
    message: InterAgentMessage
    artifact: Artifact
    payload_data_class: PayloadDataClass
    sanitizer_policy_version: str
    sanitized_payload: SanitizedInterAgentPayload


@dataclass(frozen=True)
class _MessageTail:
    seq_no: int
    payload_hash: str


class InterAgentPublisherService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def publish(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        sender_actor_id: UUID,
        request: InterAgentPublishRequest,
    ) -> InterAgentPublishResult:
        return await self._publish(
            tenant_id=tenant_id,
            project_id=project_id,
            sender_actor_id=sender_actor_id,
            request=request,
            trusted_grant=None,
        )

    async def publish_trusted_instruction(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        sender_actor_id: UUID,
        request: InterAgentPublishRequest,
        trusted_grant: TrustedInstructionGrant,
    ) -> InterAgentPublishResult:
        return await self._publish(
            tenant_id=tenant_id,
            project_id=project_id,
            sender_actor_id=sender_actor_id,
            request=request,
            trusted_grant=trusted_grant,
        )

    async def _publish(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        sender_actor_id: UUID,
        request: InterAgentPublishRequest,
        trusted_grant: TrustedInstructionGrant | None,
    ) -> InterAgentPublishResult:
        await ensure_tenant_context(self.session, tenant_id)
        self._assert_not_expired(request.expires_at)

        await self._assert_run_boundary(
            tenant_id=tenant_id,
            project_id=project_id,
            request=request,
        )
        if trusted_grant is not None:
            await self._assert_trusted_instruction_grant(
                tenant_id=tenant_id,
                project_id=project_id,
                sender_actor_id=sender_actor_id,
                request=request,
                trusted_grant=trusted_grant,
            )
        sanitizer_policy_version = await self._current_sanitizer_policy_version(
            tenant_id=tenant_id,
        )
        classification = classify_payload_data_class(request.classification)
        try:
            sanitized = sanitize_inter_agent_payload(
                request.payload,
                schema_version=request.schema_version,
                sanitizer_policy_version=sanitizer_policy_version,
            )
        except InterAgentPayloadRejected as exc:
            await InterAgentEventWriter(self.session).append_publish_denied(
                tenant_id=tenant_id,
                project_id=project_id,
                parent_run_id=request.parent_run_id,
                idempotency_key=request.idempotency_key,
                denial_reason=exc.reason_code,
                actor_id=sender_actor_id,
            )
            raise InterAgentPublishError(exc.reason_code) from exc

        await self._lock_parent_stream(
            tenant_id=tenant_id,
            project_id=project_id,
            parent_run_id=request.parent_run_id,
        )
        tail = await self._current_tail(
            tenant_id=tenant_id,
            project_id=project_id,
            parent_run_id=request.parent_run_id,
        )

        artifact = await ArtifactRepository(self.session).create_artifact(
            tenant_id=tenant_id,
            run_id=request.sender_run_id,
            project_id=project_id,
            kind="other",
            content_hash=sanitized.payload_hash,
            content_jsonb=sanitized.content_jsonb,
            payload_data_class=classification.payload_data_class,
            exportable=False,
        )

        message = InterAgentMessage(
            tenant_id=tenant_id,
            project_id=project_id,
            parent_run_id=request.parent_run_id,
            child_run_id=request.child_run_id,
            sender_actor_id=sender_actor_id,
            sender_run_id=request.sender_run_id,
            receiver_kind=request.receiver_kind,
            receiver_ref=request.receiver_ref,
            payload_data_class=classification.payload_data_class,
            trust_level=(
                "trusted_instruction" if trusted_grant is not None else "untrusted_content"
            ),
            approval_request_id=(
                trusted_grant.approval_request_id if trusted_grant is not None else None
            ),
            source_artifact_id=(
                trusted_grant.source_artifact_id if trusted_grant is not None else None
            ),
            artifact_hash=trusted_grant.artifact_hash if trusted_grant is not None else None,
            policy_version=(
                trusted_grant.policy_version if trusted_grant is not None else None
            ),
            provider_request_fingerprint=(
                trusted_grant.provider_request_fingerprint
                if trusted_grant is not None
                else None
            ),
            action_class=trusted_grant.action_class if trusted_grant is not None else None,
            payload_hash=sanitized.payload_hash,
            artifact_ref=f"artifact://inter-agent/{artifact.id}",
            seq_no=tail.seq_no + 1 if tail is not None else 1,
            previous_hash=tail.payload_hash if tail is not None else None,
            schema_version=request.schema_version,
            idempotency_key=request.idempotency_key,
            expires_at=request.expires_at,
        )
        self.session.add(message)
        await self.session.flush()
        await InterAgentEventWriter(self.session).append_sent(
            message=message,
            actor_id=sender_actor_id,
        )

        return InterAgentPublishResult(
            message=message,
            artifact=artifact,
            payload_data_class=classification.payload_data_class,
            sanitizer_policy_version=sanitizer_policy_version,
            sanitized_payload=sanitized,
        )

    async def _assert_trusted_instruction_grant(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        sender_actor_id: UUID,
        request: InterAgentPublishRequest,
        trusted_grant: TrustedInstructionGrant,
    ) -> None:
        if trusted_grant.action_class not in TRUSTED_INTER_AGENT_ACTION_CLASSES:
            raise InterAgentPublishError("trusted_instruction action_class is not allowed.")
        for field_name in (
            "artifact_hash",
            "policy_version",
            "provider_request_fingerprint",
        ):
            value = getattr(trusted_grant, field_name)
            if not isinstance(value, str) or not value.strip():
                raise InterAgentPublishError(f"{field_name} must be non-empty.")

        approval = await self.session.scalar(
            sa.select(ApprovalRequest).where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.id == trusted_grant.approval_request_id,
            )
        )
        if approval is None:
            raise InterAgentPublishError("approval_request_id not found.")
        if approval.run_id != request.sender_run_id:
            raise InterAgentPublishError("approval_request_id run boundary mismatch.")
        if approval.requested_by_actor_id != sender_actor_id:
            raise InterAgentPublishError("approval requester must match sender_actor_id.")
        if approval.status != "approved":
            raise InterAgentPublishError("approval_request_id must be approved.")
        if approval.decided_by_actor_id is None:
            raise InterAgentPublishError("approval_request_id must have a decider.")

        decider_type = await self.session.scalar(
            sa.select(Actor.actor_type).where(
                Actor.tenant_id == tenant_id,
                Actor.id == approval.decided_by_actor_id,
            )
        )
        if decider_type != "human":
            raise InterAgentPublishError("approval decider must be a human actor.")

        expected = {
            "artifact_hash": approval.artifact_hash,
            "policy_version": approval.policy_version,
            "provider_request_fingerprint": approval.provider_request_fingerprint,
            "action_class": approval.action_class,
        }
        actual = {
            "artifact_hash": trusted_grant.artifact_hash,
            "policy_version": trusted_grant.policy_version,
            "provider_request_fingerprint": trusted_grant.provider_request_fingerprint,
            "action_class": trusted_grant.action_class,
        }
        for field_name, expected_value in expected.items():
            if actual[field_name] != expected_value:
                raise InterAgentPublishError(
                    f"approval target mismatch: {field_name}."
                )

        artifact = await self.session.scalar(
            sa.select(Artifact).where(
                Artifact.tenant_id == tenant_id,
                Artifact.project_id == project_id,
                Artifact.run_id == request.sender_run_id,
                Artifact.id == trusted_grant.source_artifact_id,
            )
        )
        if artifact is None:
            raise InterAgentPublishError("source_artifact_id not found in project.")
        if artifact.content_hash != trusted_grant.artifact_hash:
            raise InterAgentPublishError("source_artifact_id content_hash mismatch.")

    @staticmethod
    def _assert_not_expired(expires_at: datetime) -> None:
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise InterAgentPublishError("expires_at must be timezone-aware.")
        now = datetime.now(tz=UTC)
        if expires_at <= now:
            raise InterAgentPublishError("expires_at must be in the future.")

    async def _assert_run_boundary(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        request: InterAgentPublishRequest,
    ) -> None:
        run_ids = {request.parent_run_id, request.sender_run_id}
        if request.child_run_id is not None:
            run_ids.add(request.child_run_id)

        result = await self.session.execute(
            sa.select(AgentRun).where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.project_id == project_id,
                AgentRun.id.in_(run_ids),
            )
        )
        runs = {run.id: run for run in result.scalars()}

        parent = runs.get(request.parent_run_id)
        if parent is None:
            raise InterAgentPublishError("parent_run_id not found in tenant/project boundary.")

        sender = runs.get(request.sender_run_id)
        if sender is None:
            raise InterAgentPublishError("sender_run_id not found in tenant/project boundary.")
        if sender.parent_run_id != request.parent_run_id:
            raise InterAgentPublishError("sender_run_id must be a child of parent_run_id.")

        if request.child_run_id is not None:
            child = runs.get(request.child_run_id)
            if child is None:
                raise InterAgentPublishError("child_run_id not found in tenant/project boundary.")
            if child.parent_run_id != request.parent_run_id:
                raise InterAgentPublishError("child_run_id must be a child of parent_run_id.")
            if child.id == request.sender_run_id:
                raise InterAgentPublishError("sender_run_id must differ from child_run_id.")

    async def _current_sanitizer_policy_version(self, *, tenant_id: int) -> str:
        result = await self.session.scalar(
            sa.text(
                """
                select version
                  from sanitizer_policy_versions
                 where tenant_id = :tenant_id
                   and deprecated_at is null
                 order by activated_at desc, version desc
                 limit 1
                """
            ),
            {"tenant_id": tenant_id},
        )
        if not isinstance(result, str) or not result.strip():
            raise InterAgentPublishError("active sanitizer_policy_versions row not found.")
        return result

    async def _lock_parent_stream(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        parent_run_id: UUID,
    ) -> None:
        await self.session.execute(
            sa.text("select pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {
                "lock_key": (
                    f"inter-agent-message:{tenant_id}:{project_id}:{parent_run_id}"
                )
            },
        )

    async def _current_tail(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        parent_run_id: UUID,
    ) -> _MessageTail | None:
        row = (
            await self.session.execute(
                sa.select(InterAgentMessage.seq_no, InterAgentMessage.payload_hash)
                .where(
                    InterAgentMessage.tenant_id == tenant_id,
                    InterAgentMessage.project_id == project_id,
                    InterAgentMessage.parent_run_id == parent_run_id,
                )
                .order_by(InterAgentMessage.seq_no.desc())
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        return _MessageTail(seq_no=int(row.seq_no), payload_hash=str(row.payload_hash))


__all__ = [
    "InterAgentPublishError",
    "InterAgentPublishResult",
    "InterAgentPublisherService",
    "TRUSTED_INTER_AGENT_ACTION_CLASSES",
    "TrustedInstructionGrant",
    "TrustedInterAgentActionClass",
]
