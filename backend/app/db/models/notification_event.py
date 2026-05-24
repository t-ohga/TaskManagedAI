from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, CreatedAtMixin, JsonDict, TenantIdMixin

NotificationSeverity = Literal["info", "low", "medium", "high", "critical"]
NotificationRequiredAction = Literal[
    "acknowledge",
    "review_approval",
    "inspect_run",
    "resolve_blocker",
    "external_followup",
]


class NotificationEvent(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "notification_events"
    __table_args__ = (
        sa.CheckConstraint(
            "severity in ('info','low','medium','high','critical')",
            name="notification_events_ck_severity",
        ),
        sa.CheckConstraint(
            "required_action in "
            "('acknowledge','review_approval','inspect_run','resolve_blocker','external_followup')",
            name="notification_events_ck_required_action",
        ),
        sa.CheckConstraint(
            "(resolved_at is null and resolved_by_actor_id is null) "
            "or (resolved_at is not null and resolved_by_actor_id is not null)",
            name="notification_events_ck_resolved_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="notification_events_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recipient_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="notification_events_recipient_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resolved_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="notification_events_resolved_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="notification_events_uq_tenant_id"),
        sa.Index(
            "notification_events_idx_triage_open",
            "tenant_id",
            "recipient_actor_id",
            "severity",
            "due_at",
            "created_at",
            postgresql_where=sa.text("resolved_at is null"),
        ),
        sa.Index(
            "notification_events_uq_open_dedupe",
            "tenant_id",
            "recipient_actor_id",
            "dedupe_key",
            unique=True,
            postgresql_where=sa.text("dedupe_key is not null and resolved_at is null"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    recipient_actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    severity: Mapped[NotificationSeverity] = mapped_column(
        sa.Text,
        nullable=False,
        server_default=sa.text("'info'"),
    )
    required_action: Mapped[NotificationRequiredAction] = mapped_column(
        sa.Text,
        nullable=False,
        server_default=sa.text("'acknowledge'"),
    )
    due_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    resolved_by_actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    dedupe_key: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


__all__ = ["NotificationEvent", "NotificationRequiredAction", "NotificationSeverity"]
