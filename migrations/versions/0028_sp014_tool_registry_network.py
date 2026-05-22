"""SP-014 batch 0d: Tool Registry network enum.

Revision ID: 0028_sp014_tool_registry_network
Revises: 0027_sp014_policy_profile
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_sp014_tool_registry_network"
down_revision: str | None = "0027_sp014_policy_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")

NETWORK_ACCESS_CHECK = "network_access in ('none','allowlist','internet')"
TRANSPORT_CHECK = "transport in ('local','stdio')"
AUTH_MODE_CHECK = "auth_mode in ('none','env_ref')"
TRUST_TIER_CHECK = "trust_tier in ('official','self_hosted','third_party','experimental')"
PAYLOAD_DATA_CLASS_CHECK = "payload_data_class_max in ('public','internal','confidential','pii')"


def upgrade() -> None:
    op.create_table(
        "tool_registry",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("tool_key", sa.Text(), nullable=False),
        sa.Column("transport", sa.Text(), nullable=False),
        sa.Column("auth_mode", sa.Text(), nullable=False),
        sa.Column("network_access", sa.Text(), server_default=sa.text("'none'"), nullable=False),
        sa.Column("trust_tier", sa.Text(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(TRANSPORT_CHECK, name="tool_registry_ck_transport"),
        sa.CheckConstraint(AUTH_MODE_CHECK, name="tool_registry_ck_auth_mode"),
        sa.CheckConstraint(NETWORK_ACCESS_CHECK, name="tool_registry_ck_network_access"),
        sa.CheckConstraint(TRUST_TIER_CHECK, name="tool_registry_ck_trust_tier"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="tool_registry_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="tool_registry_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="tool_registry_uq_tenant_id"),
        sa.UniqueConstraint("tenant_id", "tool_key", name="tool_registry_uq_tool_key"),
    )
    op.create_index(
        "tool_registry_idx_tenant_network_access",
        "tool_registry",
        ["tenant_id", "network_access"],
    )

    op.create_table(
        "tool_network_policies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain_allowlist", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_data_class_max", sa.Text(), nullable=False),
        sa.Column(
            "provider_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(domain_allowlist) = 'array'",
            name="tool_network_policies_ck_domain_allowlist_array",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(domain_allowlist) > 0",
            name="tool_network_policies_ck_domain_allowlist_non_empty",
        ),
        sa.CheckConstraint(
            PAYLOAD_DATA_CLASS_CHECK,
            name="tool_network_policies_ck_payload_data_class_max",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="tool_network_policies_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tool_id"],
            ["tool_registry.tenant_id", "tool_registry.id"],
            name="tool_network_policies_tool_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="tool_network_policies_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="tool_network_policies_uq_tenant_id"),
        sa.UniqueConstraint("tenant_id", "tool_id", name="tool_network_policies_uq_tool"),
    )

    _seed_default_tool_registry()
    _create_tool_registry_seed_trigger()


def downgrade() -> None:
    op.execute("drop trigger if exists tenants_seed_tool_registry_network on tenants")
    op.execute("drop function if exists seed_tool_registry_network_for_tenant()")
    op.drop_table("tool_network_policies")
    op.drop_index("tool_registry_idx_tenant_network_access", table_name="tool_registry")
    op.drop_table("tool_registry")


def _seed_default_tool_registry() -> None:
    op.execute(
        """
        insert into tool_registry (
            tenant_id,
            tool_key,
            transport,
            auth_mode,
            network_access,
            trust_tier,
            manifest,
            metadata
        )
        select tenants.id, tools.tool_key, 'local', 'none', 'none', 'official',
               jsonb_build_object(
                 'registry_version', 'sp014-batch-0d',
                 'allowed_actions', jsonb_build_array(tools.tool_key),
                 'deny_only', true,
                 'reason_code', 'tool_network_access_none_denied'
               ),
               '{"rls_ready": true, "seed_version": "sp014-batch-0d"}'::jsonb
          from tenants
          cross join (
            values ('web_fetch'), ('docs_search')
          ) as tools(tool_key)
        on conflict (tenant_id, tool_key) do nothing
        """
    )


def _create_tool_registry_seed_trigger() -> None:
    op.execute(
        """
        create or replace function seed_tool_registry_network_for_tenant()
            returns trigger
            language plpgsql
        as $$
        begin
            insert into tool_registry (
                tenant_id,
                tool_key,
                transport,
                auth_mode,
                network_access,
                trust_tier,
                manifest,
                metadata
            )
            values
              (
                NEW.id,
                'web_fetch',
                'local',
                'none',
                'none',
                'official',
                jsonb_build_object(
                  'registry_version', 'sp014-batch-0d',
                  'allowed_actions', jsonb_build_array('web_fetch'),
                  'deny_only', true,
                  'reason_code', 'tool_network_access_none_denied'
                ),
                '{"rls_ready": true, "seed_version": "sp014-batch-0d"}'::jsonb
              ),
              (
                NEW.id,
                'docs_search',
                'local',
                'none',
                'none',
                'official',
                jsonb_build_object(
                  'registry_version', 'sp014-batch-0d',
                  'allowed_actions', jsonb_build_array('docs_search'),
                  'deny_only', true,
                  'reason_code', 'tool_network_access_none_denied'
                ),
                '{"rls_ready": true, "seed_version": "sp014-batch-0d"}'::jsonb
              )
            on conflict (tenant_id, tool_key) do nothing;

            return NEW;
        end;
        $$;
        """
    )
    op.execute(
        """
        create trigger tenants_seed_tool_registry_network
            after insert on tenants
            for each row execute function seed_tool_registry_network_for_tenant();
        """
    )
