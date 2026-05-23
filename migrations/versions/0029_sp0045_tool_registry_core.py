"""SP-0045: Tool Registry core columns and versions.

Revision ID: 0029_sp0045_tool_registry_core
Revises: 0028_sp014_tool_registry_network
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_sp0045_tool_registry_core"
down_revision: str | None = "0028_sp014_tool_registry_network"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW_DEFAULT = sa.text("now()")
TENANT_ID_DEFAULT = sa.text("1")
RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")

ALLOWED_ACTIONS_CHECK = (
    "jsonb_typeof(allowed_actions) = 'array' "
    "and jsonb_array_length(allowed_actions) > 0 "
    "and not jsonb_path_exists("
    "allowed_actions, '$[*] ? (@.type() != \"string\")'::jsonpath"
    ") "
    "and not jsonb_path_exists("
    "allowed_actions, "
    "'$[*] ? (@ != \"web_fetch\" && @ != \"docs_search\" "
    "&& @ != \"code_grep\" && @ != \"filesystem_read\")'::jsonpath"
    ")"
)
MAX_OUTGOING_DATA_CLASS_CHECK = (
    "max_outgoing_data_class in ('public','internal','confidential','pii')"
)
REGISTRY_VERSION_CHECK = "length(registry_version) > 0"
ALLOWLIST_HASH_CHECK = "allowlist_hash ~ '^[a-f0-9]{64}$'"


def upgrade() -> None:
    op.add_column(
        "tool_registry",
        sa.Column("registry_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "tool_registry",
        sa.Column(
            "allowed_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "tool_registry",
        sa.Column("max_outgoing_data_class", sa.Text(), nullable=True),
    )

    op.execute(
        """
        update tool_registry
           set registry_version = coalesce(
                 nullif(manifest->>'registry_version', ''),
                 'sp0045-v1'
               ),
               allowed_actions = case
                 when jsonb_typeof(manifest->'allowed_actions') = 'array'
                  and jsonb_array_length(manifest->'allowed_actions') > 0
                 then manifest->'allowed_actions'
                 else jsonb_build_array(tool_key)
               end,
               max_outgoing_data_class = 'public'
         where registry_version is null
            or allowed_actions is null
            or max_outgoing_data_class is null
        """
    )

    op.alter_column("tool_registry", "registry_version", nullable=False)
    op.alter_column("tool_registry", "allowed_actions", nullable=False)
    op.alter_column("tool_registry", "max_outgoing_data_class", nullable=False)
    op.create_check_constraint(
        "tool_registry_ck_registry_version_non_empty",
        "tool_registry",
        REGISTRY_VERSION_CHECK,
    )
    op.create_check_constraint(
        "tool_registry_ck_allowed_actions",
        "tool_registry",
        ALLOWED_ACTIONS_CHECK,
    )
    op.create_check_constraint(
        "tool_registry_ck_max_outgoing_data_class",
        "tool_registry",
        MAX_OUTGOING_DATA_CLASS_CHECK,
    )

    op.create_table(
        "tool_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registry_version", sa.Text(), nullable=False),
        sa.Column("allowlist_hash", sa.Text(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            REGISTRY_VERSION_CHECK,
            name="tool_versions_ck_registry_version_non_empty",
        ),
        sa.CheckConstraint(
            ALLOWLIST_HASH_CHECK,
            name="tool_versions_ck_allowlist_hash_sha256_hex",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(manifest) = 'object'",
            name="tool_versions_ck_manifest_object",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="tool_versions_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tool_id"],
            ["tool_registry.tenant_id", "tool_registry.id"],
            name="tool_versions_tool_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="tool_versions_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="tool_versions_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "tool_id",
            "registry_version",
            name="tool_versions_uq_tool_registry_version",
        ),
    )
    op.create_index(
        "tool_versions_idx_tenant_registry_version",
        "tool_versions",
        ["tenant_id", "registry_version"],
    )

    _replace_tool_registry_seed_trigger()


def downgrade() -> None:
    _restore_sp014_tool_registry_seed_trigger()
    op.drop_index("tool_versions_idx_tenant_registry_version", table_name="tool_versions")
    op.drop_table("tool_versions")
    op.drop_constraint(
        "tool_registry_ck_max_outgoing_data_class",
        "tool_registry",
        type_="check",
    )
    op.drop_constraint("tool_registry_ck_allowed_actions", "tool_registry", type_="check")
    op.drop_constraint(
        "tool_registry_ck_registry_version_non_empty",
        "tool_registry",
        type_="check",
    )
    op.drop_column("tool_registry", "max_outgoing_data_class")
    op.drop_column("tool_registry", "allowed_actions")
    op.drop_column("tool_registry", "registry_version")


def _replace_tool_registry_seed_trigger() -> None:
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
                registry_version,
                allowed_actions,
                max_outgoing_data_class,
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
                'sp0045-v1',
                jsonb_build_array('web_fetch'),
                'public',
                jsonb_build_object(
                  'registry_version', 'sp0045-v1',
                  'allowed_actions', jsonb_build_array('web_fetch'),
                  'deny_only', true,
                  'reason_code', 'tool_network_access_none_denied'
                ),
                '{"rls_ready": true, "seed_version": "sp0045-v1"}'::jsonb
              ),
              (
                NEW.id,
                'docs_search',
                'local',
                'none',
                'none',
                'official',
                'sp0045-v1',
                jsonb_build_array('docs_search'),
                'public',
                jsonb_build_object(
                  'registry_version', 'sp0045-v1',
                  'allowed_actions', jsonb_build_array('docs_search'),
                  'deny_only', true,
                  'reason_code', 'tool_network_access_none_denied'
                ),
                '{"rls_ready": true, "seed_version": "sp0045-v1"}'::jsonb
              )
            on conflict (tenant_id, tool_key) do nothing;

            return NEW;
        end;
        $$;
        """
    )


def _restore_sp014_tool_registry_seed_trigger() -> None:
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
