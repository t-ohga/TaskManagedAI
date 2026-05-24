from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, TenantIdMixin
from backend.app.domain.artifact.data_class import PayloadDataClass
from backend.app.domain.artifact.trust_level import TrustLevel
from backend.app.domain.policy.action_class import ActionClass

InterAgentReceiverKind = Literal["agent_run", "role", "broadcast"]


class InterAgentMessage(TenantIdMixin, Base):
    """Inter-agent message metadata with ref-only payload boundaries."""

    __tablename__ = "inter_agent_messages"
    __table_args__ = (
        sa.CheckConstraint(
            "receiver_kind in ('agent_run','role','broadcast')",
            name="inter_agent_messages_ck_receiver_kind",
        ),
        sa.CheckConstraint(
            "payload_data_class in ('public','internal','confidential','pii')",
            name="inter_agent_messages_ck_payload_data_class",
        ),
        sa.CheckConstraint(
            "trust_level in ('untrusted_content','validated_artifact','trusted_instruction')",
            name="inter_agent_messages_ck_trust_level",
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="inter_agent_messages_ck_payload_hash_sha256_hex",
        ),
        sa.CheckConstraint(
            "previous_hash is null or previous_hash ~ '^[0-9a-f]{64}$'",
            name="inter_agent_messages_ck_previous_hash_sha256_hex",
        ),
        sa.CheckConstraint(
            "artifact_hash is null or artifact_hash ~ '^[0-9a-f]{64}$'",
            name="inter_agent_messages_ck_artifact_hash_sha256_hex",
        ),
        sa.CheckConstraint(
            "length(artifact_ref) > 0",
            name="inter_agent_messages_ck_artifact_ref_non_empty",
        ),
        sa.CheckConstraint(
            "length(schema_version) > 0",
            name="inter_agent_messages_ck_schema_version_non_empty",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) > 0",
            name="inter_agent_messages_ck_idempotency_key_non_empty",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="inter_agent_messages_ck_expires_after_created",
        ),
        sa.CheckConstraint(
            "(consumed_at is null and consumed_by_run_id is null) "
            "or (consumed_at is not null and consumed_by_run_id is not null)",
            name="inter_agent_messages_ck_consumed_state_consistency",
        ),
        sa.CheckConstraint(
            "((receiver_kind = 'agent_run' and child_run_id is not null and receiver_ref is null) "
            "or (receiver_kind = 'role' and child_run_id is null "
            "and nullif(receiver_ref, '') is not null) "
            "or (receiver_kind = 'broadcast' and child_run_id is null and receiver_ref is null))",
            name="inter_agent_messages_ck_receiver_target_consistency",
        ),
        sa.CheckConstraint(
            "consumed_by_run_id is null or sender_run_id <> consumed_by_run_id",
            name="inter_agent_messages_ck_sender_not_consumer",
        ),
        sa.CheckConstraint(
            "action_class is null or action_class in ("
            "'task_write','repo_write','pr_open','secret_access','provider_call')",
            name="inter_agent_messages_ck_action_class_subset",
        ),
        sa.CheckConstraint(
            "trust_level <> 'trusted_instruction' "
            "or (approval_request_id is not null "
            "and source_artifact_id is not null "
            "and artifact_hash is not null "
            "and policy_version is not null "
            "and provider_request_fingerprint is not null "
            "and action_class is not null "
            "and action_class in ("
            "'task_write','repo_write','pr_open','secret_access','provider_call'))",
            name="inter_agent_messages_ck_trusted_instruction_refs",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="inter_agent_messages_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="inter_agent_messages_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "parent_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="inter_agent_messages_parent_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "child_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="inter_agent_messages_child_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "sender_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="inter_agent_messages_sender_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "consumed_by_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="inter_agent_messages_consumed_by_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sender_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="inter_agent_messages_sender_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_request_id"],
            ["approval_requests.tenant_id", "approval_requests.id"],
            name="inter_agent_messages_approval_request_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "source_artifact_id"],
            ["artifacts.tenant_id", "artifacts.project_id", "artifacts.id"],
            name="inter_agent_messages_source_artifact_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="inter_agent_messages_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "parent_run_id",
            "seq_no",
            name="inter_agent_messages_uq_tenant_project_parent_seq",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "parent_run_id",
            "idempotency_key",
            name="inter_agent_messages_uq_tenant_project_parent_idempotency",
        ),
        sa.Index(
            "inter_agent_messages_idx_unconsumed",
            "tenant_id",
            "project_id",
            "parent_run_id",
            "seq_no",
            postgresql_where=sa.text("consumed_at is null"),
        ),
        sa.Index(
            "inter_agent_messages_idx_receiver",
            "tenant_id",
            "project_id",
            "parent_run_id",
            "receiver_kind",
            "receiver_ref",
            postgresql_where=sa.text("consumed_at is null"),
        ),
        sa.Index(
            "inter_agent_messages_idx_sender_run",
            "tenant_id",
            "project_id",
            "sender_run_id",
        ),
        sa.Index("inter_agent_messages_idx_expires_at", "tenant_id", "expires_at"),
        {
            "comment": (
                "Inter-agent message contract: payload is stored by artifact_ref "
                "and payload_hash, while audit and AgentRunEvent rows remain ref-only."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    parent_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    child_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    sender_actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sender_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    receiver_kind: Mapped[InterAgentReceiverKind] = mapped_column(sa.Text, nullable=False)
    receiver_ref: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    payload_data_class: Mapped[PayloadDataClass] = mapped_column(sa.Text, nullable=False)
    trust_level: Mapped[TrustLevel] = mapped_column(
        sa.Text,
        nullable=False,
        default="untrusted_content",
        server_default=sa.text("'untrusted_content'"),
    )
    approval_request_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    source_artifact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    artifact_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    policy_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    provider_request_fingerprint: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
    )
    action_class: Mapped[ActionClass | None] = mapped_column(sa.Text, nullable=True)
    payload_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    artifact_ref: Mapped[str] = mapped_column(sa.Text, nullable=False)
    seq_no: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    schema_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    consumed_by_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )


__all__ = ["InterAgentMessage", "InterAgentReceiverKind"]
