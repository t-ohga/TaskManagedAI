"""SP-018 batch T02: memory records and retrieval artifacts schema.

Revision ID: 0032_sp018_memory_records
Revises: 0031_sp016_api_capability_tokens
Create Date: 2026-05-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032_sp018_memory_records"
down_revision: str | None = "0031_sp016_api_capability_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW_DEFAULT = sa.text("now()")
TENANT_ID_DEFAULT = sa.text("1")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")

MEMORY_RECORD_KIND_CHECK = (
    "record_kind in ("
    "'manual_user','manual_agent','auto_completion','auto_failure','auto_review_finding')"
)
MEMORY_DATA_CLASS_CHECK = "data_class in ('public','internal','confidential','pii')"
MEMORY_REDACTION_STATUS_CHECK = "redaction_status in ('redacted','raw_with_canary_scan_passed')"
MEMORY_RECORD_TRUST_LEVEL_CHECK = "trust_level in ('untrusted_content','validated_artifact')"
MEMORY_RETRIEVAL_TRUST_LEVEL_CHECK = "trust_level = 'untrusted_content'"
SHA256_CHECK = "{column} ~ '^[0-9a-f]{{64}}$'"


def upgrade() -> None:
    op.create_table(
        "memory_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("record_kind", sa.Text(), nullable=False),
        sa.Column("content_artifact_ref", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("data_class", sa.Text(), nullable=False),
        sa.Column("redaction_status", sa.Text(), server_default=sa.text("'redacted'"), nullable=False),
        sa.Column("sanitizer_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "trust_level",
            sa.Text(),
            server_default=sa.text("'untrusted_content'"),
            nullable=False,
        ),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(MEMORY_RECORD_KIND_CHECK, name="memory_records_ck_record_kind"),
        sa.CheckConstraint(
            SHA256_CHECK.format(column="content_hash"),
            name="memory_records_ck_content_hash_sha256_hex",
        ),
        sa.CheckConstraint(MEMORY_DATA_CLASS_CHECK, name="memory_records_ck_data_class"),
        sa.CheckConstraint(
            MEMORY_REDACTION_STATUS_CHECK,
            name="memory_records_ck_redaction_status",
        ),
        sa.CheckConstraint(
            MEMORY_RECORD_TRUST_LEVEL_CHECK,
            name="memory_records_ck_trust_level_no_trusted_instruction",
        ),
        sa.CheckConstraint(
            "length(content_artifact_ref) > 0",
            name="memory_records_ck_content_artifact_ref_non_empty",
        ),
        sa.CheckConstraint(
            "retention_until > created_at",
            name="memory_records_ck_retention_after_created",
        ),
        sa.CheckConstraint(
            "archived_at is null or archived_at >= created_at",
            name="memory_records_ck_archived_after_created",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="memory_records_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="memory_records_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sanitizer_version_id"],
            ["sanitizer_policy_versions.tenant_id", "sanitizer_policy_versions.id"],
            name="memory_records_sanitizer_policy_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "source_artifact_id"],
            ["artifacts.tenant_id", "artifacts.project_id", "artifacts.id"],
            name="memory_records_source_artifact_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="memory_records_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="memory_records_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="memory_records_uq_tenant_project_id",
        ),
        comment=(
            "Project-scoped memory metadata. Redacted content lives in artifact "
            "storage and is referenced by content_artifact_ref + content_hash."
        ),
    )
    op.create_index(
        "memory_records_idx_tenant_project_kind_created",
        "memory_records",
        ["tenant_id", "project_id", "record_kind", "created_at"],
    )
    op.create_index(
        "memory_records_idx_active_retention",
        "memory_records",
        ["tenant_id", "project_id", "retention_until"],
        postgresql_where=sa.text("archived_at is null"),
    )

    op.create_table(
        "memory_retrieval_artifacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retrieval_artifact_ref", sa.Text(), nullable=False),
        sa.Column("retrieval_hash", sa.Text(), nullable=False),
        sa.Column("sanitizer_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retrieval_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("context_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "trust_level",
            sa.Text(),
            server_default=sa.text("'untrusted_content'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            SHA256_CHECK.format(column="retrieval_hash"),
            name="memory_retrieval_artifacts_ck_retrieval_hash_sha256_hex",
        ),
        sa.CheckConstraint(
            MEMORY_RETRIEVAL_TRUST_LEVEL_CHECK,
            name="memory_retrieval_artifacts_ck_trust_level_untrusted",
        ),
        sa.CheckConstraint(
            "length(retrieval_artifact_ref) > 0",
            name="memory_retrieval_artifacts_ck_retrieval_artifact_ref_non_empty",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="memory_retrieval_artifacts_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="memory_retrieval_artifacts_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "memory_record_id"],
            ["memory_records.tenant_id", "memory_records.project_id", "memory_records.id"],
            name="memory_retrieval_artifacts_memory_record_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sanitizer_version_id"],
            ["sanitizer_policy_versions.tenant_id", "sanitizer_policy_versions.id"],
            name="memory_retrieval_artifacts_sanitizer_policy_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "retrieval_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="memory_retrieval_artifacts_retrieval_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "context_snapshot_id"],
            ["context_snapshots.tenant_id", "context_snapshots.id"],
            name="memory_retrieval_artifacts_context_snapshot_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="memory_retrieval_artifacts_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="memory_retrieval_artifacts_uq_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="memory_retrieval_artifacts_uq_tenant_project_id",
        ),
        comment=(
            "Memory retrieval metadata remains untrusted_content and points to "
            "artifact-bound snippets rather than raw prompt text."
        ),
    )
    op.create_index(
        "memory_retrieval_artifacts_idx_tenant_project_record_created",
        "memory_retrieval_artifacts",
        ["tenant_id", "project_id", "memory_record_id", "created_at"],
    )
    op.create_index(
        "memory_retrieval_artifacts_idx_retrieval_run",
        "memory_retrieval_artifacts",
        ["tenant_id", "project_id", "retrieval_run_id"],
        postgresql_where=sa.text("retrieval_run_id is not null"),
    )


def downgrade() -> None:
    op.drop_index(
        "memory_retrieval_artifacts_idx_retrieval_run",
        table_name="memory_retrieval_artifacts",
    )
    op.drop_index(
        "memory_retrieval_artifacts_idx_tenant_project_record_created",
        table_name="memory_retrieval_artifacts",
    )
    op.drop_table("memory_retrieval_artifacts")
    op.drop_index("memory_records_idx_active_retention", table_name="memory_records")
    op.drop_index(
        "memory_records_idx_tenant_project_kind_created",
        table_name="memory_records",
    )
    op.drop_table("memory_records")
