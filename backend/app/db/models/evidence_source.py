from __future__ import annotations

from datetime import datetime
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


class EvidenceSource(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "evidence_sources"
    __table_args__ = (
        sa.CheckConstraint(
            "length(canonical_url) between 1 and 2000",
            name="evidence_sources_ck_canonical_url_length",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[a-f0-9]{64}$'",
            name="evidence_sources_ck_content_hash_sha256_hex",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="evidence_sources_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="evidence_sources_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "canonical_url",
            name="evidence_sources_uq_tenant_canonical_url",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    canonical_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["EvidenceSource"]
