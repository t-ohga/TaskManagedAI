from __future__ import annotations

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
from backend.app.domain.policy.action_class import ActionClass, PolicyEffect


class PolicyDecision(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (
        sa.CheckConstraint(
            "action_class in "
            "('task_write','repo_write','pr_open','secret_access','merge','deploy','provider_call')",
            name="policy_decisions_ck_action_class",
        ),
        sa.CheckConstraint(
            "decision in ('allow','deny','require_approval')",
            name="policy_decisions_ck_decision",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="policy_decisions_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approval_request_id"],
            ["approval_requests.tenant_id", "approval_requests.id"],
            name="policy_decisions_approval_request_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="policy_decisions_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="policy_decisions_uq_tenant_id"),
        sa.Index("policy_decisions_idx_tenant_action_class", "tenant_id", "action_class"),
        sa.Index(
            "policy_decisions_idx_tenant_approval",
            "tenant_id",
            "approval_request_id",
            postgresql_where=sa.text("approval_request_id is not null"),
        ),
        sa.Index("policy_decisions_idx_created_at", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    # TODO Sprint 4: add FK (tenant_id, run_id) -> agent_runs(tenant_id, id).
    run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    approval_request_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    action_class: Mapped[ActionClass] = mapped_column(sa.Text, nullable=False)
    decision: Mapped[PolicyEffect] = mapped_column(sa.Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(sa.Text, nullable=False)
    policy_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["PolicyDecision"]

