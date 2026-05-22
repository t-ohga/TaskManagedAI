"""Multi-agent orchestration foundation phase A: project_agent_roles + standard_role_ids_mirror.

SP-013 batch 0b (ADR-00014 §2 + ADR-00019 §1 + PE-F-012 mitigation).

新規 2 table:
1. `project_agent_roles`: project-scoped custom role table
2. `standard_role_ids_mirror`: 10 standard roles の immutable seed (PE-F-012 DB-level CHECK 用)

scope 外 (次 batch):
- agent_runs 拡張 (role_id / role_scope / orchestrator_lease_* / progress_seq)
- sanitizer_policy_versions table
- check_project_role_link() trigger 関数
- contract test 群

Revision ID: 0020_multi_agent_foundation_a
Revises: 0019_artifacts_project_id
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_multi_agent_foundation_a"
down_revision: str | None = "0019_artifacts_project_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")

# ADR-00019 §1 採用案: 10 standard role taxonomy (immutable seed)
STANDARD_ROLES: list[tuple[str, str, str]] = [
    ("orchestrator", "Orchestrator", "Multi-agent coordination, requester only"),
    ("implementer", "Implementer", "Code implementation"),
    ("reviewer", "Reviewer", "Code review"),
    ("tester", "Tester", "Test implementation and execution"),
    ("security_agent", "Security Agent", "Security audit"),
    ("researcher", "Researcher", "Research and evidence collection"),
    ("observer", "Observer", "Observability and metrics"),
    ("curator", "Curator", "Docs and Sprint Pack curation"),
    ("dispatcher", "Dispatcher", "Task dispatching and queue management"),
    ("repair_specialist", "Repair Specialist", "Failure repair and retry orchestration"),
]


def upgrade() -> None:
    # 1. project_agent_roles: project-scoped custom role table (ADR-00014 §2)
    op.create_table(
        "project_agent_roles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "recommended_provider_tier",
            sa.Text(),
            server_default=sa.text("'balanced'"),
            nullable=False,
        ),
        sa.Column("icon_ref", sa.Text(), nullable=True),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        # ADR-00014 §2 CHECK: role_id pattern (snake_case identifier、2-32 chars)
        sa.CheckConstraint(
            "role_id ~ '^[a-z][a-z0-9_]{1,31}$'",
            name="project_agent_roles_ck_role_id_pattern",
        ),
        sa.CheckConstraint(
            "recommended_provider_tier in ('balanced','high-quality','low-cost','mock')",
            name="project_agent_roles_ck_provider_tier",
        ),
        # primary key + composite unique constraints (project boundary 強制)
        sa.PrimaryKeyConstraint("id", name="project_agent_roles_pk"),
        sa.UniqueConstraint("tenant_id", "id", name="project_agent_roles_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "id",
            name="project_agent_roles_uq_tenant_project_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "role_id",
            name="project_agent_roles_uq_tenant_project_role",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="project_agent_roles_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="project_agent_roles_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="project_agent_roles_created_by_fkey",
            ondelete="RESTRICT",
        ),
    )

    op.create_index(
        "project_agent_roles_idx_tenant_project_role",
        "project_agent_roles",
        ["tenant_id", "project_id", "role_id"],
    )

    # 2. standard_role_ids_mirror: 10 standard role taxonomy の immutable seed
    # PE-F-012 mitigation: DB-level CHECK enforcement 用、application layer (taxonomy.py) の
    # frozenset と 5+ source 整合の一翼を担う。
    op.create_table(
        "standard_role_ids_mirror",
        sa.Column("role_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.PrimaryKeyConstraint("role_id", name="standard_role_ids_mirror_pk"),
        sa.CheckConstraint(
            "role_id ~ '^[a-z][a-z0-9_]{1,31}$'",
            name="standard_role_ids_mirror_ck_role_id_pattern",
        ),
    )

    # immutable seed: 10 standard role taxonomy (ADR-00019 §1)
    op.bulk_insert(
        sa.table(
            "standard_role_ids_mirror",
            sa.column("role_id", sa.Text),
            sa.column("display_name", sa.Text),
            sa.column("description", sa.Text),
        ),
        [
            {"role_id": rid, "display_name": dn, "description": desc}
            for rid, dn, desc in STANDARD_ROLES
        ],
    )


def downgrade() -> None:
    op.drop_table("standard_role_ids_mirror")
    op.drop_index(
        "project_agent_roles_idx_tenant_project_role",
        table_name="project_agent_roles",
    )
    op.drop_table("project_agent_roles")
