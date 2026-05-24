"""SP-015 batch 0a: inter-agent messages schema.

Revision ID: 0030_sp015_inter_agent_messages
Revises: 0029_sp0045_tool_registry_core
Create Date: 2026-05-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_sp015_inter_agent_messages"
down_revision: str | None = "0029_sp0045_tool_registry_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW_DEFAULT = sa.text("now()")
TENANT_ID_DEFAULT = sa.text("1")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")

RECEIVER_KIND_CHECK = "receiver_kind in ('agent_run','role','broadcast')"
PAYLOAD_DATA_CLASS_CHECK = "payload_data_class in ('public','internal','confidential','pii')"
TRUST_LEVEL_CHECK = "trust_level in ('untrusted_content','validated_artifact','trusted_instruction')"
SHA256_OR_NULL = "{column} is null or {column} ~ '^[0-9a-f]{{64}}$'"
TRUSTED_INSTRUCTION_REFS_CHECK = (
    "trust_level <> 'trusted_instruction' "
    "or (approval_request_id is not null "
    "and source_artifact_id is not null "
    "and artifact_hash is not null "
    "and policy_version is not null "
    "and provider_request_fingerprint is not null "
    "and action_class is not null "
    "and action_class in ("
    "'task_write','repo_write','pr_open','secret_access','provider_call'))"
)
ACTION_CLASS_SUBSET_CHECK = (
    "action_class is null or action_class in ("
    "'task_write','repo_write','pr_open','secret_access','provider_call')"
)
RECEIVER_TARGET_CHECK = (
    "((receiver_kind = 'agent_run' and child_run_id is not null and receiver_ref is null) "
    "or (receiver_kind = 'role' and child_run_id is null "
    "and nullif(receiver_ref, '') is not null) "
    "or (receiver_kind = 'broadcast' and child_run_id is null and receiver_ref is null))"
)
CONSUMED_STATE_CHECK = (
    "(consumed_at is null and consumed_by_run_id is null) "
    "or (consumed_at is not null and consumed_by_run_id is not null)"
)


def upgrade() -> None:
    op.create_table(
        "inter_agent_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("child_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sender_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("receiver_kind", sa.Text(), nullable=False),
        sa.Column("receiver_ref", sa.Text(), nullable=True),
        sa.Column("payload_data_class", sa.Text(), nullable=False),
        sa.Column(
            "trust_level",
            sa.Text(),
            server_default=sa.text("'untrusted_content'"),
            nullable=False,
        ),
        sa.Column("approval_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("artifact_hash", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.Text(), nullable=True),
        sa.Column("provider_request_fingerprint", sa.Text(), nullable=True),
        sa.Column("action_class", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("artifact_ref", sa.Text(), nullable=False),
        sa.Column("seq_no", sa.BigInteger(), nullable=False),
        sa.Column("previous_hash", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_by_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(RECEIVER_KIND_CHECK, name="inter_agent_messages_ck_receiver_kind"),
        sa.CheckConstraint(
            PAYLOAD_DATA_CLASS_CHECK,
            name="inter_agent_messages_ck_payload_data_class",
        ),
        sa.CheckConstraint(TRUST_LEVEL_CHECK, name="inter_agent_messages_ck_trust_level"),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="inter_agent_messages_ck_payload_hash_sha256_hex",
        ),
        sa.CheckConstraint(
            SHA256_OR_NULL.format(column="previous_hash"),
            name="inter_agent_messages_ck_previous_hash_sha256_hex",
        ),
        sa.CheckConstraint(
            SHA256_OR_NULL.format(column="artifact_hash"),
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
            CONSUMED_STATE_CHECK,
            name="inter_agent_messages_ck_consumed_state_consistency",
        ),
        sa.CheckConstraint(
            RECEIVER_TARGET_CHECK,
            name="inter_agent_messages_ck_receiver_target_consistency",
        ),
        sa.CheckConstraint(
            "consumed_by_run_id is null or sender_run_id <> consumed_by_run_id",
            name="inter_agent_messages_ck_sender_not_consumer",
        ),
        sa.CheckConstraint(
            ACTION_CLASS_SUBSET_CHECK,
            name="inter_agent_messages_ck_action_class_subset",
        ),
        sa.CheckConstraint(
            TRUSTED_INSTRUCTION_REFS_CHECK,
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
        sa.PrimaryKeyConstraint("id", name="inter_agent_messages_pkey"),
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
        comment=(
            "Inter-agent message contract: payload is stored by artifact_ref "
            "and payload_hash, while audit and AgentRunEvent rows remain ref-only."
        ),
    )
    op.create_index(
        "inter_agent_messages_idx_unconsumed",
        "inter_agent_messages",
        ["tenant_id", "project_id", "parent_run_id", "seq_no"],
        postgresql_where=sa.text("consumed_at is null"),
    )
    op.create_index(
        "inter_agent_messages_idx_receiver",
        "inter_agent_messages",
        ["tenant_id", "project_id", "parent_run_id", "receiver_kind", "receiver_ref"],
        postgresql_where=sa.text("consumed_at is null"),
    )
    op.create_index(
        "inter_agent_messages_idx_sender_run",
        "inter_agent_messages",
        ["tenant_id", "project_id", "sender_run_id"],
    )
    op.create_index(
        "inter_agent_messages_idx_expires_at",
        "inter_agent_messages",
        ["tenant_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("inter_agent_messages_idx_expires_at", table_name="inter_agent_messages")
    op.drop_index("inter_agent_messages_idx_sender_run", table_name="inter_agent_messages")
    op.drop_index("inter_agent_messages_idx_receiver", table_name="inter_agent_messages")
    op.drop_index("inter_agent_messages_idx_unconsumed", table_name="inter_agent_messages")
    op.drop_table("inter_agent_messages")
