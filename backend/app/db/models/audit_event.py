from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, CreatedAtMixin, JsonDict, TenantIdMixin


class AuditEvent(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        sa.CheckConstraint(
            "(principal_id is null) or (actor_id is not null)",
            name="audit_events_ck_principal_requires_actor",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="audit_events_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="audit_events_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id", "principal_id"],
            ["principals.tenant_id", "principals.actor_id", "principals.id"],
            name="audit_events_actor_principal_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="audit_events_uq_tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    event_payload: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    principal_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


__all__ = ["AuditEvent"]

