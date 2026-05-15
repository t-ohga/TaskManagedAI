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
    UpdatedAtMixin,
    rls_ready_metadata,
)


class Claim(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "claims"
    __table_args__ = (
        sa.CheckConstraint(
            "length(claim_text) between 1 and 2000",
            name="claims_ck_claim_text_length",
        ),
        sa.CheckConstraint(
            "freshness_score is null or (freshness_score >= 0.0 and freshness_score <= 1.0)",
            name="claims_ck_freshness_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="claims_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "research_task_id"],
            ["research_tasks.tenant_id", "research_tasks.project_id", "research_tasks.id"],
            name="claims_research_task_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="claims_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="claims_uq_tenant_project_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    research_task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    claim_text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provenance_json: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    freshness_score: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )

    def __repr__(self) -> str:
        return (
            f"Claim(id={self.id!s}, tenant_id={self.tenant_id!r}, "
            f"project_id={self.project_id!s})"
        )


__all__ = ["Claim"]
