"""SP-014 batch 0b: review_artifacts four-layer defense.

Adds the agent-level review_artifacts table used by ADR-00014 Tier 2
auto-allow policy input. This migration intentionally does not connect
policy_decisions.required_review_artifact_id; that belongs to SP-014 batch 0c.

Revision ID: 0026_sp014_review_artifacts
Revises: 0025_sp014_event_type_37
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_sp014_review_artifacts"
down_revision: str | None = "0025_sp014_event_type_37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")


def upgrade() -> None:
    op.create_table(
        "review_artifacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requester_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_target_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_class", sa.Text(), nullable=False),
        sa.Column("target_artifact_hash", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("provider_request_fingerprint_hash", sa.Text(), nullable=False),
        sa.Column("review_verdict", sa.Text(), nullable=False),
        sa.Column(
            "findings_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.PrimaryKeyConstraint("id", name="review_artifacts_pk"),
        sa.UniqueConstraint("tenant_id", "id", name="review_artifacts_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="review_artifacts_uq_tenant_project_id",
        ),
        sa.CheckConstraint(
            "action_class in ('task_write','repo_write','pr_open','secret_access')",
            name="review_artifacts_ck_action_class",
        ),
        sa.CheckConstraint(
            "review_verdict in ('pass','fail','needs_revision')",
            name="review_artifacts_ck_review_verdict",
        ),
        sa.CheckConstraint(
            "findings_count >= 0",
            name="review_artifacts_ck_findings_count_nonnegative",
        ),
        sa.CheckConstraint(
            "target_artifact_hash ~ '^[0-9a-f]{64}$'",
            name="review_artifacts_ck_target_artifact_hash_sha256",
        ),
        sa.CheckConstraint(
            "provider_request_fingerprint_hash ~ '^[0-9a-f]{64}$'",
            name="review_artifacts_ck_provider_request_fingerprint_hash_sha256",
        ),
        sa.CheckConstraint(
            "length(btrim(policy_version)) > 0",
            name="review_artifacts_ck_policy_version_nonempty",
        ),
        sa.CheckConstraint(
            "reviewer_run_id <> requester_run_id",
            name="review_artifacts_ck_reviewer_not_requester",
        ),
        sa.CheckConstraint(
            "review_artifact_id <> review_target_artifact_id",
            name="review_artifacts_ck_review_artifact_differs",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="review_artifacts_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="review_artifacts_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "parent_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="review_artifacts_parent_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "requester_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="review_artifacts_requester_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "reviewer_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="review_artifacts_reviewer_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "review_target_artifact_id"],
            ["artifacts.tenant_id", "artifacts.project_id", "artifacts.id"],
            name="review_artifacts_target_artifact_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "review_artifact_id"],
            ["artifacts.tenant_id", "artifacts.project_id", "artifacts.id"],
            name="review_artifacts_review_artifact_fkey",
            ondelete="RESTRICT",
        ),
        comment=(
            "Agent-level review artifact with reviewer/requester separation, "
            "project-bound artifact FKs, and policy input hash binding."
        ),
    )

    op.create_index(
        "review_artifacts_idx_tenant_project_parent",
        "review_artifacts",
        ["tenant_id", "project_id", "parent_run_id", "created_at"],
    )
    op.create_index(
        "review_artifacts_idx_tenant_project_reviewer",
        "review_artifacts",
        ["tenant_id", "project_id", "reviewer_run_id", "created_at"],
    )
    op.create_index(
        "review_artifacts_idx_target_action",
        "review_artifacts",
        ["tenant_id", "project_id", "review_target_artifact_id", "action_class"],
    )


def downgrade() -> None:
    op.drop_index(
        "review_artifacts_idx_target_action",
        table_name="review_artifacts",
    )
    op.drop_index(
        "review_artifacts_idx_tenant_project_reviewer",
        table_name="review_artifacts",
    )
    op.drop_index(
        "review_artifacts_idx_tenant_project_parent",
        table_name="review_artifacts",
    )
    op.drop_table("review_artifacts")
