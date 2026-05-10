from __future__ import annotations

from typing import Literal
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

AcceptanceCriteriaStatus = Literal["pending", "satisfied", "rejected", "deferred"]


class AcceptanceCriteria(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "acceptance_criteria"
    __table_args__ = (
        sa.CheckConstraint(
            "status in ('pending','satisfied','rejected','deferred')",
            name="acceptance_criteria_ck_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="acceptance_criteria_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="acceptance_criteria_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "ticket_id"],
            ["tickets.tenant_id", "tickets.project_id", "tickets.id"],
            name="acceptance_criteria_ticket_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="acceptance_criteria_uq_tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    ticket_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[AcceptanceCriteriaStatus] = mapped_column(
        sa.Text,
        nullable=False,
        default="pending",
        server_default=sa.text("'pending'"),
    )
    evidence_ref: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["AcceptanceCriteria", "AcceptanceCriteriaStatus"]

