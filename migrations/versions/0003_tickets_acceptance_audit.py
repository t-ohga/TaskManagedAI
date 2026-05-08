"""Add tickets, acceptance criteria, relations, audit, and notification tables.

Revision ID: 0003_tickets_acceptance_audit
Revises: 0002_tenants_actors_principals
Create Date: 2026-05-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_tickets_acceptance_audit"
down_revision: str | None = "0002_tenants_actors_principals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("priority", sa.Text(), nullable=True),
        sa.Column("assignee_actor_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="tickets_ck_slug_url_safe",
        ),
        sa.CheckConstraint(
            "status in ('open','in_progress','blocked','review','closed','cancelled')",
            name="tickets_ck_status",
        ),
        sa.CheckConstraint(
            "priority in ('low','medium','high','critical')",
            name="tickets_ck_priority",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="tickets_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="tickets_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "repository_id"],
            ["repositories.tenant_id", "repositories.id"],
            name="tickets_repository_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "repository_id"],
            ["repositories.tenant_id", "repositories.project_id", "repositories.id"],
            name="tickets_repository_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assignee_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="tickets_assignee_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="tickets_created_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="tickets_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="tickets_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="tickets_uq_tenant_project_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "slug",
            name="tickets_uq_tenant_project_slug",
        ),
    )

    op.create_table(
        "acceptance_criteria",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "status in ('pending','satisfied','rejected','deferred')",
            name="acceptance_criteria_ck_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="acceptance_criteria_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="acceptance_criteria_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "ticket_id"],
            ["tickets.tenant_id", "tickets.project_id", "tickets.id"],
            name="acceptance_criteria_ticket_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="acceptance_criteria_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="acceptance_criteria_uq_tenant_id"),
    )

    op.create_table(
        "ticket_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "relation_type in ('blocks','blocked_by','duplicates','relates_to','depends_on')",
            name="ticket_relations_ck_relation_type",
        ),
        sa.CheckConstraint(
            "source_ticket_id != target_ticket_id",
            name="ticket_relations_ck_no_self_loop",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="ticket_relations_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="ticket_relations_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "source_ticket_id"],
            ["tickets.tenant_id", "tickets.project_id", "tickets.id"],
            name="ticket_relations_source_ticket_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "target_ticket_id"],
            ["tickets.tenant_id", "tickets.project_id", "tickets.id"],
            name="ticket_relations_target_ticket_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="ticket_relations_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="ticket_relations_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="ticket_relations_uq_tenant_project_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "source_ticket_id",
            "target_ticket_id",
            "relation_type",
            name="ticket_relations_uq_edge",
        ),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="audit_events_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="audit_events_uq_tenant_id"),
    )

    op.create_table(
        "notification_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recipient_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="notification_events_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="notification_events_uq_tenant_id"),
    )

    op.create_index("tickets_idx_project_status", "tickets", ["tenant_id", "project_id", "status"])
    op.create_index("tickets_idx_created_by_actor", "tickets", ["tenant_id", "created_by_actor_id"])
    op.create_index(
        "tickets_idx_assignee_actor",
        "tickets",
        ["tenant_id", "assignee_actor_id"],
        postgresql_where=sa.text("assignee_actor_id is not null"),
    )
    op.create_index(
        "tickets_idx_repository",
        "tickets",
        ["tenant_id", "project_id", "repository_id"],
        postgresql_where=sa.text("repository_id is not null"),
    )
    op.create_index(
        "acceptance_criteria_idx_ticket",
        "acceptance_criteria",
        ["tenant_id", "project_id", "ticket_id"],
    )
    op.create_index(
        "ticket_relations_idx_source",
        "ticket_relations",
        ["tenant_id", "project_id", "source_ticket_id"],
    )
    op.create_index(
        "ticket_relations_idx_target",
        "ticket_relations",
        ["tenant_id", "project_id", "target_ticket_id"],
    )
    op.create_index(
        "audit_events_idx_trace",
        "audit_events",
        ["tenant_id", "trace_id"],
        postgresql_where=sa.text("trace_id is not null"),
    )
    op.create_index(
        "audit_events_idx_correlation",
        "audit_events",
        ["tenant_id", "correlation_id"],
        postgresql_where=sa.text("correlation_id is not null"),
    )
    op.create_index(
        "audit_events_idx_event_type",
        "audit_events",
        ["tenant_id", "event_type", "created_at"],
    )
    op.create_index(
        "notification_events_idx_unread_recipient",
        "notification_events",
        ["tenant_id", "recipient_actor_id", "created_at"],
        postgresql_where=sa.text("read_at is null"),
    )

    op.execute(
        """
        CREATE TRIGGER tickets_set_updated_at
        BEFORE UPDATE ON tickets
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER acceptance_criteria_set_updated_at
        BEFORE UPDATE ON acceptance_criteria
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS acceptance_criteria_set_updated_at ON acceptance_criteria")
    op.execute("DROP TRIGGER IF EXISTS tickets_set_updated_at ON tickets")

    op.drop_table("notification_events")
    op.drop_table("audit_events")
    op.drop_table("ticket_relations")
    op.drop_table("acceptance_criteria")
    op.drop_table("tickets")

