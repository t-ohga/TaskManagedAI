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
    rls_ready_metadata,
)


class ApprovalRevisionRequest(TenantIdMixin, CreatedAtMixin, Base):
    """Human request to revise a pending approval without expanding approval status enum."""

    __tablename__ = "approval_revision_requests"
    __table_args__ = (
        sa.CheckConstraint(
            "btrim(rationale) <> '' and char_length(rationale) <= 2000",
            name="approval_revision_requests_ck_rationale",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="approval_revision_requests_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_request_id"],
            ["approval_requests.tenant_id", "approval_requests.id"],
            name="approval_revision_requests_approval_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="approval_revision_requests_requested_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "superseded_by_approval_request_id"],
            ["approval_requests.tenant_id", "approval_requests.id"],
            name="approval_revision_requests_superseded_by_approval_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="approval_revision_requests_uq_tenant_id",
        ),
        sa.Index(
            "approval_revision_requests_uq_open_approval",
            "tenant_id",
            "approval_request_id",
            unique=True,
            postgresql_where=sa.text("superseded_by_approval_request_id is null"),
        ),
        sa.Index(
            "approval_revision_requests_idx_approval",
            "tenant_id",
            "approval_request_id",
        ),
        sa.Index(
            "approval_revision_requests_idx_requested_by",
            "tenant_id",
            "requested_by_actor_id",
            "created_at",
        ),
        sa.Index(
            "approval_revision_requests_idx_superseded_by",
            "tenant_id",
            "superseded_by_approval_request_id",
            postgresql_where=sa.text("superseded_by_approval_request_id is not null"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    approval_request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    requested_by_actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    rationale: Mapped[str] = mapped_column(sa.Text, nullable=False)
    artifact_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    diff_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    policy_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    policy_pack_lock: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    provider_request_fingerprint: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    stale_after_event_seq: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    superseded_by_approval_request_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime]
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["ApprovalRevisionRequest"]
