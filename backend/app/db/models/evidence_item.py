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


class EvidenceItem(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "evidence_items"
    __table_args__ = (
        sa.CheckConstraint(
            "length(locator) between 1 and 500",
            name="evidence_items_ck_locator_length",
        ),
        sa.CheckConstraint(
            "relation in ('supports', 'contradicts', 'context')",
            name="evidence_items_ck_relation_enum",
        ),
        sa.CheckConstraint(
            "relevance_score is null or (relevance_score >= 0.0 and relevance_score <= 1.0)",
            name="evidence_items_ck_relevance_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="evidence_items_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "claim_id"],
            ["claims.tenant_id", "claims.project_id", "claims.id"],
            name="evidence_items_claim_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["evidence_sources.tenant_id", "evidence_sources.id"],
            name="evidence_items_source_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="evidence_items_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "claim_id",
            "source_id",
            "locator",
            name="evidence_items_uq_claim_source_locator",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    locator: Mapped[str] = mapped_column(sa.Text, nullable=False)
    relation: Mapped[str] = mapped_column(sa.Text, nullable=False)
    relevance_score: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )

    def __repr__(self) -> str:
        return (
            f"EvidenceItem(id={self.id!s}, tenant_id={self.tenant_id!r}, "
            f"project_id={self.project_id!s})"
        )


__all__ = ["EvidenceItem"]
