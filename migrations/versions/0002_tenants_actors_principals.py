"""Add tenant-aware core identity and project tables.

Revision ID: 0002_tenants_actors_principals
Revises: 0001_init_schema
Create Date: 2026-05-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_tenants_actors_principals"
down_revision: str | None = "0001_init_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS trigger AS $$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.PrimaryKeyConstraint("id", name="tenants_pkey"),
        sa.UniqueConstraint("name", name="tenants_uq_name"),
    )

    op.execute(
        """
        INSERT INTO tenants (id, name, metadata)
        VALUES (
          1,
          'default-tenant',
          '{"rls_ready": true, "seed_version": "sprint2"}'::jsonb
        )
        ON CONFLICT (id) DO NOTHING
        """
    )

    op.create_table(
        "actors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            server_default=TENANT_ID_DEFAULT,
            nullable=False,
        ),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("auth_context_hash", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("impersonated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "actor_type in ('human','service','agent','provider','github_app')",
            name="actors_ck_actor_type",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="actors_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "impersonated_by"],
            ["actors.tenant_id", "actors.id"],
            name="actors_impersonated_by_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="actors_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="actors_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_id",
            name="actors_uq_tenant_actor_id",
        ),
    )

    op.create_table(
        "principals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            server_default=TENANT_ID_DEFAULT,
            nullable=False,
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_type", sa.Text(), nullable=False),
        sa.Column("auth_context_hash", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "principal_type in "
            "('session','api_token','capability_token','installation','worker')",
            name="principals_ck_principal_type",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="principals_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="principals_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="principals_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="principals_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_id",
            "id",
            name="principals_uq_tenant_actor_principal_id",
        ),
    )

    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            server_default=TENANT_ID_DEFAULT,
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("owner_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="workspaces_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="workspaces_owner_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="workspaces_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="workspaces_uq_tenant_id"),
        sa.UniqueConstraint("tenant_id", "slug", name="workspaces_uq_tenant_slug"),
    )

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            server_default=TENANT_ID_DEFAULT,
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("policy_profile", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "status in ('active','archived')",
            name="projects_ck_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="projects_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workspace_id"],
            ["workspaces.tenant_id", "workspaces.id"],
            name="projects_workspace_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="projects_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="projects_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "slug",
            name="projects_uq_tenant_workspace_slug",
        ),
    )

    op.create_table(
        "repositories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            server_default=TENANT_ID_DEFAULT,
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("owner_name", sa.Text(), nullable=False),
        sa.Column("repo_name", sa.Text(), nullable=False),
        sa.Column("default_branch", sa.Text(), server_default=sa.text("'main'"), nullable=False),
        sa.Column("installation_ref", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "provider in ('github','gitlab','bitbucket')",
            name="repositories_ck_provider",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="repositories_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="repositories_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="repositories_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="repositories_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="repositories_uq_tenant_project_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "external_id",
            name="repositories_uq_tenant_provider_external",
        ),
    )

    op.execute(
        """
        CREATE TRIGGER tenants_set_updated_at
        BEFORE UPDATE ON tenants
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER actors_set_updated_at
        BEFORE UPDATE ON actors
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER workspaces_set_updated_at
        BEFORE UPDATE ON workspaces
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER projects_set_updated_at
        BEFORE UPDATE ON projects
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER repositories_set_updated_at
        BEFORE UPDATE ON repositories
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS repositories_set_updated_at ON repositories")
    op.execute("DROP TRIGGER IF EXISTS projects_set_updated_at ON projects")
    op.execute("DROP TRIGGER IF EXISTS workspaces_set_updated_at ON workspaces")
    op.execute("DROP TRIGGER IF EXISTS actors_set_updated_at ON actors")
    op.execute("DROP TRIGGER IF EXISTS tenants_set_updated_at ON tenants")

    op.drop_table("repositories")
    op.drop_table("projects")
    op.drop_table("workspaces")
    op.drop_table("principals")
    op.drop_table("actors")
    op.drop_table("tenants")

    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")

