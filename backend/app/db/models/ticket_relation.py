from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import (
    Base,
    CreatedAtMixin,
    JsonDict,
    TenantIdMixin,
    rls_ready_metadata,
)

TicketRelationType = Literal["blocks", "blocked_by", "duplicates", "relates_to", "depends_on"]


class TicketRelation(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "ticket_relations"
    __table_args__ = (
        sa.CheckConstraint(
            "relation_type in ('blocks','blocked_by','duplicates','relates_to','depends_on')",
            name="ticket_relations_ck_relation_type",
        ),
        sa.CheckConstraint(
            "source_ticket_id != target_ticket_id",
            name="ticket_relations_ck_no_self_loop",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="ticket_relations_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="ticket_relations_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "source_ticket_id"],
            ["tickets.tenant_id", "tickets.project_id", "tickets.id"],
            name="ticket_relations_source_ticket_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "target_ticket_id"],
            ["tickets.tenant_id", "tickets.project_id", "tickets.id"],
            name="ticket_relations_target_ticket_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="ticket_relations_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="ticket_relations_uq_tenant_project_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "source_ticket_id",
            "target_ticket_id",
            "relation_type",
            name="ticket_relations_uq_edge",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_ticket_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    target_ticket_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    relation_type: Mapped[TicketRelationType] = mapped_column(sa.Text, nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["TicketRelation", "TicketRelationType"]

