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

# ADR-00044: 固定 color palette (UI / caller 自由入力不可)。5+ source 整合の Python Literal 側。
# DB CHECK (migrations/versions/0042) / Pydantic / pytest EXPECTED と一致させる。
TagColor = Literal[
    "slate", "red", "orange", "amber", "green", "teal", "blue", "purple", "pink"
]

TAG_COLORS: tuple[TagColor, ...] = (
    "slate", "red", "orange", "amber", "green", "teal", "blue", "purple", "pink"
)


class Tag(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """project-scoped な ticket tag entity (ADR-00044 A-5)。"""

    __tablename__ = "tags"
    __table_args__ = (
        sa.CheckConstraint(
            "char_length(name) between 1 and 50",
            name="tags_ck_name_length",
        ),
        sa.CheckConstraint(
            "color in (" + ", ".join(f"'{c}'" for c in TAG_COLORS) + ")",
            name="tags_ck_color",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="tags_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="tags_project_fkey",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="tags_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "id", name="tags_uq_tenant_project_id"
        ),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "name", name="tags_uq_tenant_project_name"
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    color: Mapped[TagColor] = mapped_column(sa.Text, nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


class TicketTag(TenantIdMixin, CreatedAtMixin, Base):
    """ticket と tag の association (ADR-00044)。純粋 join table のため metadata 列を持たない
    (RLS は親 tickets / tags 側で enforce)。FK2 (tag) は ON DELETE RESTRICT で使用中 tag 削除を拒否。
    """

    __tablename__ = "ticket_tags"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="ticket_tags_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "ticket_id"],
            ["tickets.tenant_id", "tickets.project_id", "tickets.id"],
            name="ticket_tags_ticket_fkey",
            ondelete="CASCADE",
        ),
        # ADR-00044 R6: ON DELETE RESTRICT。両 FK が (tenant_id, project_id) を共有し同一 project 強制。
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "tag_id"],
            ["tags.tenant_id", "tags.project_id", "tags.id"],
            name="ticket_tags_tag_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "project_id", "ticket_id", "tag_id", name="ticket_tags_pkey"
        ),
        sa.Index("ticket_tags_ix_tag", "tenant_id", "project_id", "tag_id"),
    )

    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    ticket_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    tag_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


__all__ = ["Tag", "TicketTag", "TagColor", "TAG_COLORS"]
