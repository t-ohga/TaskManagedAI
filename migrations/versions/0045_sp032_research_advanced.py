"""SP-032 research advanced: conflict_groups + domain_trust_registry + claims.conflict_group_id.

Revision ID: 0045_sp032_research_advanced
Revises: 0044_sp028_webhook_events
Create Date: 2026-06-09 00:00:00.000000

ADR-00052. SP-010 BL-0121 placeholder (conflict_group_id / domain trust registry) の P1 activation。
- conflict_groups: research_task-scoped、claims.conflict_group_id を 4-col 複合 FK で同一 research_task に束縛。
- domain_trust_registry: tenant-scoped (project boundary なし、evidence_sources と同 scope)。
- claims.conflict_group_id: nullable additive 列、ON DELETE RESTRICT (conflict_groups は hard delete 不可)。

additive のみ。conflict status / trust_tier の CHECK は 5+ source integrity の DB 側 (ADR-00052 §R1)。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0045_sp032_research_advanced"
down_revision: str | None = "0044_sp028_webhook_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_DEFAULT = sa.text("uuid_generate_v4()")

# ADR-00052: 5+ source integrity の DB CHECK 側 (ORM / Literal / Pydantic / pytest と exact set 整合)
CONFLICT_STATUSES = ("open", "resolved", "dismissed")
TRUST_TIERS = ("low", "medium", "high")


def upgrade() -> None:
    # 1. conflict_groups (research_task-scoped)
    op.create_table(
        "conflict_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=UUID_DEFAULT, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("research_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "char_length(title) between 1 and 200",
            name="conflict_groups_ck_title_length",
        ),
        sa.CheckConstraint(
            "status in (" + ", ".join(f"'{s}'" for s in CONFLICT_STATUSES) + ")",
            name="conflict_groups_ck_status",
        ),
        # ADR-00052 R1 F-002: resolved のみ note 必須、dismissed は任意。
        sa.CheckConstraint(
            "status <> 'resolved' or resolution_note is not null",
            name="conflict_groups_ck_resolved_note_required",
        ),
        sa.CheckConstraint(
            "resolution_note is null or char_length(resolution_note) between 1 and 2000",
            name="conflict_groups_ck_resolution_note_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="conflict_groups_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        # research_task が同一 project に属することを DB 強制
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "research_task_id"],
            ["research_tasks.tenant_id", "research_tasks.project_id", "research_tasks.id"],
            name="conflict_groups_research_task_fkey",
            ondelete="RESTRICT",
        ),
        # ADR-00052 R1 F-011: created_by_actor は同 tenant の actor
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="conflict_groups_created_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="conflict_groups_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="conflict_groups_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "id", name="conflict_groups_uq_tenant_project_id"
        ),
        # claims.conflict_group_id の 4-col 複合 FK target (同一 research_task 強制)
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "research_task_id",
            "id",
            name="conflict_groups_uq_tenant_project_rt_id",
        ),
    )
    op.create_index(
        "conflict_groups_ix_research_task",
        "conflict_groups",
        ["tenant_id", "project_id", "research_task_id"],
    )
    op.execute(
        """
        CREATE TRIGGER conflict_groups_set_updated_at
        BEFORE UPDATE ON conflict_groups
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    # 2. domain_trust_registry (tenant-scoped、project boundary なし)
    op.create_table(
        "domain_trust_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=UUID_DEFAULT, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("trust_tier", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        # ADR-00052 R1 F-003: 厳密 format は service 層の domain_normalize、DB は length + lowercase
        # + hostname char set の緩い防御。
        sa.CheckConstraint(
            "char_length(domain) between 1 and 253",
            name="domain_trust_registry_ck_domain_length",
        ),
        sa.CheckConstraint(
            "domain = lower(domain) and domain ~ '^[a-z0-9.-]+$'",
            name="domain_trust_registry_ck_domain_format",
        ),
        sa.CheckConstraint(
            "trust_tier in (" + ", ".join(f"'{t}'" for t in TRUST_TIERS) + ")",
            name="domain_trust_registry_ck_trust_tier",
        ),
        sa.CheckConstraint(
            "rationale is null or char_length(rationale) between 1 and 1000",
            name="domain_trust_registry_ck_rationale_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="domain_trust_registry_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="domain_trust_registry_created_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="domain_trust_registry_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="domain_trust_registry_uq_tenant_id"),
        # domain ごとに最大 1 entry (正規化後)
        sa.UniqueConstraint(
            "tenant_id", "domain", name="domain_trust_registry_uq_tenant_domain"
        ),
    )
    op.execute(
        """
        CREATE TRIGGER domain_trust_registry_set_updated_at
        BEFORE UPDATE ON domain_trust_registry
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    # 3. claims.conflict_group_id (nullable additive 列 + 4-col 複合 FK)
    op.add_column(
        "claims",
        sa.Column("conflict_group_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # ADR-00052 R1 F-001: MATCH SIMPLE。conflict_group_id IS NULL は未割当で FK 検査 skip。
    # 非 NULL 時のみ 4 列で同一 (tenant, project, research_task) の conflict_group に束縛。
    op.create_foreign_key(
        "claims_conflict_group_fkey",
        "claims",
        "conflict_groups",
        ["tenant_id", "project_id", "research_task_id", "conflict_group_id"],
        ["tenant_id", "project_id", "research_task_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "claims_ix_conflict_group",
        "claims",
        ["tenant_id", "project_id", "research_task_id", "conflict_group_id"],
    )


def downgrade() -> None:
    # FK 依存順: claims FK → conflict_groups。ADR-00052 rollback 手順 (assignment export 前提)。
    op.drop_index("claims_ix_conflict_group", table_name="claims")
    op.drop_constraint("claims_conflict_group_fkey", "claims", type_="foreignkey")
    op.drop_column("claims", "conflict_group_id")

    op.execute(
        "DROP TRIGGER IF EXISTS domain_trust_registry_set_updated_at ON domain_trust_registry"
    )
    op.drop_table("domain_trust_registry")

    op.execute("DROP TRIGGER IF EXISTS conflict_groups_set_updated_at ON conflict_groups")
    op.drop_index("conflict_groups_ix_research_task", table_name="conflict_groups")
    op.drop_table("conflict_groups")
