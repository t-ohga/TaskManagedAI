from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, JsonDict, TenantIdMixin


class EvalRun(TenantIdMixin, Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        sa.CheckConstraint(
            "length(suite_name) between 1 and 100",
            name="eval_runs_ck_suite_name_length",
        ),
        sa.CheckConstraint(
            "length(provider) between 1 and 50",
            name="eval_runs_ck_provider_length",
        ),
        sa.CheckConstraint(
            "length(model) between 1 and 100",
            name="eval_runs_ck_model_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="eval_runs_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name="eval_runs_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "dataset_version_id"],
            ["dataset_versions.tenant_id", "dataset_versions.id"],
            name="eval_runs_dataset_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="eval_runs_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "dataset_version_id",
            name="eval_runs_uq_tenant_id_dataset_version",
        ),
        # F-PR28-R3-005 P2 adopt: composite unique key for future RetrievalEvalRun
        # FK target (SP-010 QL-C cross-ref).
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "run_id",
            name="eval_runs_uq_tenant_id_run",
        ),
        sa.Index(
            "eval_runs_ix_tenant_dataset_started",
            "tenant_id",
            "dataset_version_id",
            "started_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    dataset_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    suite_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provider: Mapped[str] = mapped_column(sa.Text, nullable=False)
    model: Mapped[str] = mapped_column(sa.Text, nullable=False)
    summary: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


__all__ = ["EvalRun"]
