"""Add secret reference and capability token tables.

Revision ID: 0004_secret_capability_tokens
Revises: 0003_tickets_acceptance_audit
Create Date: 2026-05-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_secret_capability_tokens"
down_revision: str | None = "0003_tickets_acceptance_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_READY_DEFAULT = sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb")
TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")
EMPTY_JSONB_ARRAY_DEFAULT = sa.text("'[]'::jsonb")
EMPTY_JSONB_OBJECT_DEFAULT = sa.text("'{}'::jsonb")
PROHIBITED_METADATA_KEYS_JSONPATH = (
    "'strict $.** ? (@.type() == \"object\")."
    "keyvalue() ? (@.key == \"raw_secret\" || @.key == \"raw_token\" "
    "|| @.key == \"api_key\" || @.key == \"auth_token\" "
    "|| @.key == \"secret_value\" || @.key == \"plaintext\" "
    "|| @.key == \"private_key\" || @.key == \"sops_key\" "
    "|| @.key == \"age_key\" || @.key == \"canary\" "
    "|| @.key == \"token\" || @.key == \"raw_value\" "
    "|| @.key == \"value\")'"
)


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.create_table(
        "secret_refs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("secret_uri", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "runner_injectable",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "allowed_consumers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=EMPTY_JSONB_ARRAY_DEFAULT,
            nullable=False,
        ),
        sa.Column(
            "allowed_operations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=EMPTY_JSONB_ARRAY_DEFAULT,
            nullable=False,
        ),
        sa.Column("owner_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rotated_from_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "secret_uri ~ '^secret://sops/(p0|workspace|project|repo|agent_run|provider)/[a-z0-9_-]+#v[0-9]+$'",
            name="secret_refs_ck_secret_uri_format",
        ),
        sa.CheckConstraint(
            "secret_uri = 'secret://sops/' || scope || '/' || name || '#' || version",
            name="secret_refs_ck_secret_uri_components_match",
        ),
        sa.CheckConstraint(
            "scope in ('p0','workspace','project','repo','agent_run','provider')",
            name="secret_refs_ck_scope",
        ),
        sa.CheckConstraint(
            "status in ('pending','active','deprecated','revoked')",
            name="secret_refs_ck_status",
        ),
        sa.CheckConstraint(
            "runner_injectable = false",
            name="secret_refs_ck_runner_injectable_false",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_consumers) = 'array' "
            "AND jsonb_typeof(allowed_operations) = 'array'",
            name="secret_refs_ck_allowlist_jsonb_arrays",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_consumers) <> 'array' "
            "OR NOT jsonb_path_exists(allowed_consumers, "
            "'strict $[*] ? (@.type() != \"string\")'::jsonpath)",
            name="secret_refs_ck_allowed_consumers_string_elements",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_operations) <> 'array' "
            "OR NOT jsonb_path_exists(allowed_operations, "
            "'strict $[*] ? (@.type() != \"string\")'::jsonpath)",
            name="secret_refs_ck_allowed_operations_string_elements",
        ),
        sa.CheckConstraint(
            "status <> 'active' "
            "OR (jsonb_array_length(allowed_consumers) > 0 "
            "AND jsonb_array_length(allowed_operations) > 0)",
            name="secret_refs_ck_active_allowlist_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object' "
            f"AND NOT jsonb_path_exists(metadata, {PROHIBITED_METADATA_KEYS_JSONPATH}::jsonpath)",
            name="secret_refs_ck_metadata_no_raw_secret",
        ),
        sa.CheckConstraint(
            "(deprecated_at is null) or (status in ('deprecated','revoked'))",
            name="secret_refs_ck_deprecated_at",
        ),
        sa.CheckConstraint(
            "(revoked_at is null) or (status = 'revoked')",
            name="secret_refs_ck_revoked_at",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="secret_refs_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="secret_refs_owner_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "rotated_from_id"],
            ["secret_refs.tenant_id", "secret_refs.id"],
            name="secret_refs_rotated_from_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="secret_refs_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="secret_refs_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "secret_uri",
            name="secret_refs_uq_tenant_secret_uri",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "scope",
            "name",
            "version",
            name="secret_refs_uq_tenant_scope_name_version",
        ),
    )

    op.create_table(
        "secret_capability_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("secret_ref_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "allowed_operations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=EMPTY_JSONB_ARRAY_DEFAULT,
            nullable=False,
        ),
        sa.Column(
            "scope_constraint",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=EMPTY_JSONB_OBJECT_DEFAULT,
            nullable=False,
        ),
        sa.Column("issued_to_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        # TODO Sprint 4: add FK (tenant_id, issued_run_id) → agent_runs(tenant_id, id)
        sa.Column("issued_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expected_request_fingerprint", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=RLS_READY_DEFAULT,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "status in ('issued','redeeming','used','expired','revoked')",
            name="secret_capability_tokens_ck_status",
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[a-f0-9]{64}$'",
            name="secret_capability_tokens_ck_token_hash_format",
        ),
        sa.CheckConstraint(
            "expected_request_fingerprint ~ '^[a-f0-9]{64}$'",
            name="secret_capability_tokens_ck_expected_request_fingerprint_format",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_operations) = 'array' "
            "AND jsonb_array_length(allowed_operations) > 0",
            name="secret_capability_tokens_ck_allowed_operations_nonempty_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_operations) <> 'array' "
            "OR NOT jsonb_path_exists(allowed_operations, "
            "'strict $[*] ? (@.type() != \"string\")'::jsonpath)",
            name="secret_capability_tokens_ck_allowed_operations_string_elements",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scope_constraint) = 'object'",
            name="secret_capability_tokens_ck_scope_constraint_jsonb_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object' "
            f"AND NOT jsonb_path_exists(metadata, {PROHIBITED_METADATA_KEYS_JSONPATH}::jsonpath)",
            name="secret_capability_tokens_ck_metadata_no_raw_secret",
        ),
        sa.CheckConstraint(
            "expires_at >= created_at + interval '5 minutes' "
            "AND expires_at <= created_at + interval '30 minutes'",
            name="secret_capability_tokens_ck_expires_within_ttl_bounds",
        ),
        sa.CheckConstraint(
            "(status = 'issued' AND used_at IS NULL) "
            "OR (status IN ('redeeming','used') AND used_at IS NOT NULL) "
            "OR status IN ('expired','revoked')",
            name="secret_capability_tokens_ck_used_at_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="secret_capability_tokens_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "secret_ref_id"],
            ["secret_refs.tenant_id", "secret_refs.id"],
            name="secret_capability_tokens_secret_ref_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "issued_to_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="secret_capability_tokens_issued_to_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="secret_capability_tokens_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="secret_capability_tokens_uq_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "token_hash",
            name="secret_capability_tokens_uq_tenant_token_hash",
        ),
    )

    op.create_index(
        "secret_refs_one_active_per_name",
        "secret_refs",
        ["tenant_id", "scope", "name"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "secret_refs_one_pending_per_name",
        "secret_refs",
        ["tenant_id", "scope", "name"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("secret_refs_idx_status", "secret_refs", ["tenant_id", "status"])
    op.create_index("secret_refs_idx_scope_name", "secret_refs", ["tenant_id", "scope", "name"])

    op.create_index(
        "secret_capability_tokens_idx_expires_at",
        "secret_capability_tokens",
        ["tenant_id", "expires_at"],
        postgresql_where=sa.text("status = 'issued'"),
    )
    op.create_index(
        "secret_capability_tokens_idx_issued_status",
        "secret_capability_tokens",
        ["tenant_id", "secret_ref_id", "status"],
        postgresql_where=sa.text("status = 'issued'"),
    )
    op.create_index(
        "secret_capability_tokens_idx_issued_actor",
        "secret_capability_tokens",
        ["tenant_id", "issued_to_actor_id"],
    )
    op.create_index(
        "secret_capability_tokens_idx_issued_run",
        "secret_capability_tokens",
        ["tenant_id", "issued_run_id"],
        postgresql_where=sa.text("issued_run_id is not null"),
    )

    op.execute(
        """
        CREATE TRIGGER secret_refs_set_updated_at
        BEFORE UPDATE ON secret_refs
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS secret_refs_set_updated_at ON secret_refs")

    op.drop_table("secret_capability_tokens")
    op.drop_table("secret_refs")

