from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, CreatedAtMixin, TenantIdMixin

# ADR-00049 (SP-034): idempotency 対象 MCP tool / resource kind。
# 5+ source 整合 (DB CHECK in migrations/versions/0043 / Pydantic / pytest EXPECTED) の Python Literal 側。
McpIdempotencyToolName = Literal["ticket_create", "run_create"]
MCP_IDEMPOTENCY_TOOL_NAMES: tuple[McpIdempotencyToolName, ...] = (
    "ticket_create",
    "run_create",
)

McpIdempotencyResourceKind = Literal["ticket", "agent_run"]
MCP_IDEMPOTENCY_RESOURCE_KINDS: tuple[McpIdempotencyResourceKind, ...] = (
    "ticket",
    "agent_run",
)


class McpIdempotencyKey(TenantIdMixin, CreatedAtMixin, Base):
    """MCP create-level idempotency reservation row (ADR-00049 SP-034)。

    reservation-first: row を先に予約 (created_resource_kind / created_resource_id / completed_at は
    NULL) し、winner だけが resource を作成して completed (3 列同時 set) にする。
    ``(tenant_id, actor_id, tool_name, idempotency_key)`` unique が cross-actor replay deny の核 (別
    actor は別 row、互いに干渉しない)。CHECK で「全 NULL (reservation 中) か 全 NOT NULL (completed)」を
    enforce し loser が半端 resource を返さないことを保証する。
    """

    __tablename__ = "mcp_idempotency_keys"
    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_id",
            "actor_id",
            "tool_name",
            "idempotency_key",
            name="mcp_idempotency_keys_uq_tenant_actor_tool_key",
        ),
        sa.CheckConstraint(
            "tool_name IN ('ticket_create', 'run_create')",
            name="mcp_idempotency_keys_tool_name_check",
        ),
        sa.CheckConstraint(
            "created_resource_kind IS NULL "
            "OR created_resource_kind IN ('ticket', 'agent_run')",
            name="mcp_idempotency_keys_resource_kind_check",
        ),
        sa.CheckConstraint(
            "(created_resource_kind IS NULL AND created_resource_id IS NULL "
            "AND completed_at IS NULL) "
            "OR (created_resource_kind IS NOT NULL AND created_resource_id IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="mcp_idempotency_keys_reservation_complete_check",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    tool_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_resource_kind: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_resource_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
