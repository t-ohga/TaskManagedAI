from __future__ import annotations

from datetime import date
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

TicketStatus = Literal["open", "in_progress", "blocked", "review", "closed", "cancelled"]
TicketPriority = Literal["low", "medium", "high", "critical"]


class Ticket(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="tickets_ck_slug_url_safe",
        ),
        sa.CheckConstraint(
            "status in ('open','in_progress','blocked','review','closed','cancelled')",
            name="tickets_ck_status",
        ),
        sa.CheckConstraint(
            "priority in ('low','medium','high','critical')",
            name="tickets_ck_priority",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="tickets_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="tickets_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "repository_id"],
            ["repositories.tenant_id", "repositories.id"],
            name="tickets_repository_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "repository_id"],
            ["repositories.tenant_id", "repositories.project_id", "repositories.id"],
            name="tickets_repository_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assignee_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="tickets_assignee_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="tickets_created_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="tickets_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="tickets_uq_tenant_project_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "slug",
            name="tickets_uq_tenant_project_slug",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    repository_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    slug: Mapped[str] = mapped_column(sa.Text, nullable=False)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[TicketStatus] = mapped_column(
        sa.Text,
        nullable=False,
        default="open",
        server_default=sa.text("'open'"),
    )
    priority: Mapped[TicketPriority | None] = mapped_column(sa.Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    assignee_actor_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_by_actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["Ticket", "TicketPriority", "TicketStatus"]

