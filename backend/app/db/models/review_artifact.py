from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, TenantIdMixin
from backend.app.domain.review_artifact import (
    ReviewArtifactActionClass,
    ReviewArtifactVerdict,
)


class ReviewArtifact(TenantIdMixin, Base):
    """Agent reviewer verdict bound to the exact reviewed policy input."""

    __tablename__ = "review_artifacts"
    __table_args__ = (
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
        sa.UniqueConstraint("tenant_id", "id", name="review_artifacts_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="review_artifacts_uq_tenant_project_id",
        ),
        sa.Index(
            "review_artifacts_idx_tenant_project_parent",
            "tenant_id",
            "project_id",
            "parent_run_id",
            "created_at",
        ),
        sa.Index(
            "review_artifacts_idx_tenant_project_reviewer",
            "tenant_id",
            "project_id",
            "reviewer_run_id",
            "created_at",
        ),
        sa.Index(
            "review_artifacts_idx_target_action",
            "tenant_id",
            "project_id",
            "review_target_artifact_id",
            "action_class",
        ),
        {
            "comment": (
                "Agent-level review artifact with reviewer/requester separation, "
                "project-bound artifact FKs, and policy input hash binding."
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
    requester_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    reviewer_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    review_target_artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )
    review_artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )
    action_class: Mapped[ReviewArtifactActionClass] = mapped_column(sa.Text, nullable=False)
    target_artifact_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    policy_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provider_request_fingerprint_hash: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
    )
    review_verdict: Mapped[ReviewArtifactVerdict] = mapped_column(sa.Text, nullable=False)
    findings_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


__all__ = ["ReviewArtifact"]
