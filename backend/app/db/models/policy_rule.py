from __future__ import annotations

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
from backend.app.domain.policy.action_class import ActionClass, PolicyEffect


class PolicyRule(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "policy_rules"
    __table_args__ = (
        sa.CheckConstraint(
            "action_class in "
            "('task_write','repo_write','pr_open','secret_access','merge','deploy','provider_call')",
            name="policy_rules_ck_action_class",
        ),
        sa.CheckConstraint(
            "effect in ('allow','deny','require_approval')",
            name="policy_rules_ck_effect",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="policy_rules_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="policy_rules_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="policy_rules_uq_tenant_id"),
        sa.Index("policy_rules_idx_tenant_action_class", "tenant_id", "action_class"),
        sa.Index("policy_rules_idx_policy_version", "tenant_id", "policy_version"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    action_class: Mapped[ActionClass] = mapped_column(sa.Text, nullable=False)
    effect: Mapped[PolicyEffect] = mapped_column(sa.Text, nullable=False)
    rule_json: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    policy_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["PolicyRule"]

