from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import (
    Base,
    JsonDict,
    TenantIdMixin,
    rls_ready_metadata,
)
from backend.app.domain.policy.action_class import ActionClass

ApprovalStatus = Literal["pending", "approved", "rejected", "expired", "invalidated"]
RiskLevel = Literal["low", "medium", "high", "critical"]


class ApprovalRequest(TenantIdMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        sa.CheckConstraint(
            "action_class in "
            "('task_write','repo_write','pr_open','secret_access','merge','deploy','provider_call')",
            name="approval_requests_ck_action_class",
        ),
        sa.CheckConstraint(
            "risk_level in ('low','medium','high','critical')",
            name="approval_requests_ck_risk_level",
        ),
        sa.CheckConstraint(
            "status in ('pending','approved','rejected','expired','invalidated')",
            name="approval_requests_ck_status",
        ),
        sa.CheckConstraint(
            "status not in ('approved','rejected') "
            "or (decided_by_actor_id is not null and decided_at is not null)",
            name="approval_requests_ck_decision_completeness",
        ),
        sa.CheckConstraint(
            "decided_by_actor_id is null or requested_by_actor_id != decided_by_actor_id",
            name="approval_requests_ck_self_approval",
        ),
        sa.CheckConstraint(
            "(decided_by_actor_id is null and decided_at is null) "
            "or (decided_by_actor_id is not null and decided_at is not null)",
            name="approval_requests_ck_decided_at_consistency",
        ),
        sa.CheckConstraint(
            "decided_at is null or decided_at >= requested_at",
            name="approval_requests_ck_decided_at_after_requested_at",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="approval_requests_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="approval_requests_requested_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "decided_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="approval_requests_decided_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="approval_requests_uq_tenant_id"),
        sa.Index("approval_requests_idx_tenant_status", "tenant_id", "status"),
        sa.Index(
            "approval_requests_idx_tenant_run",
            "tenant_id",
            "run_id",
            postgresql_where=sa.text("run_id is not null"),
        ),
        sa.Index("approval_requests_idx_requested_at", "tenant_id", "requested_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    # TODO Sprint 4: add FK (tenant_id, run_id) -> agent_runs(tenant_id, id).
    run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    action_class: Mapped[ActionClass] = mapped_column(sa.Text, nullable=False)
    resource_ref: Mapped[str] = mapped_column(sa.Text, nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(sa.Text, nullable=False)
    artifact_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    diff_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    policy_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    policy_pack_lock: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    provider_request_fingerprint: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    stale_after_event_seq: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    status: Mapped[ApprovalStatus] = mapped_column(sa.Text, nullable=False)
    requested_by_actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    decided_by_actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    rationale: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["ApprovalRequest", "ApprovalStatus", "RiskLevel"]

