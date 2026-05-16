from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import (
    Base,
    CreatedAtMixin,
    JsonDict,
    TenantIdMixin,
    rls_ready_metadata,
)


class EvalCase(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "eval_cases"
    __table_args__ = (
        sa.CheckConstraint(
            "length(case_key) between 1 and 200",
            name="eval_cases_ck_case_key_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="eval_cases_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "dataset_version_id"],
            ["dataset_versions.tenant_id", "dataset_versions.id"],
            name="eval_cases_dataset_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="eval_cases_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "dataset_version_id",
            name="eval_cases_uq_tenant_id_dataset_version",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "dataset_version_id",
            "case_key",
            name="eval_cases_uq_tenant_dataset_case_key",
        ),
        sa.Index("eval_cases_ix_tenant_dataset", "tenant_id", "dataset_version_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    dataset_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    case_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    case_json: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    expected_json: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["EvalCase"]
