from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, CreatedAtMixin, JsonDict, TenantIdMixin


class EvalScore(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "eval_scores"
    __table_args__ = (
        sa.CheckConstraint(
            "length(metric_key) between 1 and 100",
            name="eval_scores_ck_metric_key_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="eval_scores_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "eval_run_id", "dataset_version_id"],
            ["eval_runs.tenant_id", "eval_runs.id", "eval_runs.dataset_version_id"],
            name="eval_scores_eval_run_dataset_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "eval_case_id", "dataset_version_id"],
            ["eval_cases.tenant_id", "eval_cases.id", "eval_cases.dataset_version_id"],
            name="eval_scores_eval_case_dataset_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "eval_run_id",
            "eval_case_id",
            "metric_key",
            name="eval_scores_uq_tenant_run_case_metric",
        ),
        sa.Index("eval_scores_ix_tenant_run_metric", "tenant_id", "eval_run_id", "metric_key"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    eval_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    eval_case_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    dataset_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    metric_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    score: Mapped[Decimal] = mapped_column(sa.Numeric(12, 4), nullable=False)
    passed: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    details: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )


__all__ = ["EvalScore"]
