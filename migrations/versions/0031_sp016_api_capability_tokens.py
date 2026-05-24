"""SP-016 batch 0a: API capability token schema.

Revision ID: 0031_sp016_api_capability_tokens
Revises: 0030_sp015_inter_agent_messages
Create Date: 2026-05-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_sp016_api_capability_tokens"
down_revision: str | None = "0030_sp015_inter_agent_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW_DEFAULT = sa.text("now()")
TENANT_ID_DEFAULT = sa.text("1")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")
RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")

PROHIBITED_METADATA_KEYS_JSONPATH = (
    "'strict $.** ? (@.type() == \"object\")."
    "keyvalue() ? (@.key == \"raw_secret\" || @.key == \"raw_token\" "
    "|| @.key == \"api_key\" || @.key == \"auth_token\" "
    "|| @.key == \"secret_value\" || @.key == \"plaintext\" "
    "|| @.key == \"private_key\" || @.key == \"sops_key\" "
    "|| @.key == \"age_key\" || @.key == \"canary\" "
    "|| @.key == \"token\" || @.key == \"raw_value\" "
    "|| @.key == \"value\" || @.key == \"capability_token\")'"
)


def upgrade() -> None:
    op.create_table(
        "api_capability_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=True),
        sa.Column("allowed_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "scope_constraint",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "audience",
            sa.Text(),
            server_default=sa.text("'taskmanagedai-api'"),
            nullable=False,
        ),
        sa.Column("auth_context_hash", sa.Text(), nullable=False),
        sa.Column("request_binding_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'issued'"), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("jti", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('issued','expired','revoked')",
            name="api_capability_tokens_ck_status",
        ),
        sa.CheckConstraint(
            "audience = 'taskmanagedai-api'",
            name="api_capability_tokens_ck_audience",
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[a-f0-9]{64}$'",
            name="api_capability_tokens_ck_token_hash_format",
        ),
        sa.CheckConstraint(
            "auth_context_hash ~ '^[a-f0-9]{64}$'",
            name="api_capability_tokens_ck_auth_context_hash_format",
        ),
        sa.CheckConstraint(
            "request_binding_hash ~ '^[a-f0-9]{64}$'",
            name="api_capability_tokens_ck_request_binding_hash_format",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_actions) = 'array' "
            "AND jsonb_array_length(allowed_actions) > 0",
            name="api_capability_tokens_ck_allowed_actions_nonempty_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_actions) <> 'array' "
            "OR NOT jsonb_path_exists(allowed_actions, "
            "'strict $[*] ? (@.type() != \"string\")'::jsonpath)",
            name="api_capability_tokens_ck_allowed_actions_string_elements",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scope_constraint) = 'object'",
            name="api_capability_tokens_ck_scope_constraint_jsonb_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object' "
            f"AND NOT jsonb_path_exists(metadata, {PROHIBITED_METADATA_KEYS_JSONPATH}::jsonpath)",
            name="api_capability_tokens_ck_metadata_no_raw_secret",
        ),
        sa.CheckConstraint(
            "expires_at >= issued_at + interval '5 minutes' "
            "AND expires_at <= issued_at + interval '30 minutes'",
            name="api_capability_tokens_ck_expires_within_ttl_bounds",
        ),
        sa.CheckConstraint(
            "(status = 'revoked') = (revoked_at IS NOT NULL)",
            name="api_capability_tokens_ck_revoked_at_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="api_capability_tokens_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="api_capability_tokens_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id", "principal_id"],
            ["principals.tenant_id", "principals.actor_id", "principals.id"],
            name="api_capability_tokens_principal_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="api_capability_tokens_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="api_capability_tokens_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="api_capability_tokens_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "token_hash",
            name="api_capability_tokens_uq_tenant_token_hash",
        ),
        sa.UniqueConstraint("tenant_id", "jti", name="api_capability_tokens_uq_tenant_jti"),
        comment=(
            "Principal-bound API capability tokens for CLI operations. "
            "Only SHA-256 token hashes and binding fingerprints are stored."
        ),
    )
    op.create_index(
        "api_capability_tokens_idx_active",
        "api_capability_tokens",
        ["tenant_id", "actor_id", "status", "expires_at"],
    )
    op.create_index(
        "api_capability_tokens_idx_project",
        "api_capability_tokens",
        ["tenant_id", "project_id", "status", "expires_at"],
        postgresql_where=sa.text("project_id is not null"),
    )


def downgrade() -> None:
    op.drop_index("api_capability_tokens_idx_project", table_name="api_capability_tokens")
    op.drop_index("api_capability_tokens_idx_active", table_name="api_capability_tokens")
    op.drop_table("api_capability_tokens")
