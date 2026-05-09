"""Add Artifact and ContextSnapshot tables.

Revision ID: 0009_artifacts_context_snapshots
Revises: 0008_agent_runs_lifecycle
Create Date: 2026-05-09 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_artifacts_context_snapshots"
down_revision: str | None = "0008_agent_runs_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")

_PROHIBITED_PAYLOAD_KEYS: tuple[str, ...] = (
    "api_key",
    "api_token",
    "raw_secret",
    "secret",
    "secret_value",
    "private_key",
    "auth_token",
    "bearer_token",
    "capability_token",
    "capability_token_value",
    "provider_key",
    "github_installation_token",
    "github_app_private_key",
    "tailscale_auth_key",
    "sops_age_key",
    "age_private_key",
    "canary_value",
    "raw_canary",
    "secret_capability_token",
    "raw_token",
    "session_token",
)


def _prohibited_payload_keys_jsonpath() -> str:
    disjunction = " || ".join(f'@.key == "{key}"' for key in _PROHIBITED_PAYLOAD_KEYS)
    return (
        "'strict $.** ? (@.type() == \"object\")."
        f"keyvalue() ? ({disjunction})'"
    )


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("content_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_data_class", sa.Text(), nullable=False),
        sa.Column("exportable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("parent_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "kind in "
            "('plan','patch','evidence','citation','provider_continuation_ref','other')",
            name="artifacts_ck_kind",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="artifacts_ck_content_hash_sha256_hex",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(content_jsonb) = 'object'",
            name="artifacts_ck_content_jsonb_object",
        ),
        sa.CheckConstraint(
            "payload_data_class in ('public','internal','confidential','pii')",
            name="artifacts_ck_payload_data_class",
        ),
        sa.CheckConstraint(
            "(kind <> 'provider_continuation_ref') or (exportable = false)",
            name="artifacts_ck_provider_continuation_ref_not_exportable",
        ),
        sa.CheckConstraint(
            "not jsonb_path_exists(content_jsonb, "
            f"{_prohibited_payload_keys_jsonpath()}::jsonpath)",
            name="artifacts_ck_no_prohibited_payload_keys",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="artifacts_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name="artifacts_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id", "parent_artifact_id"],
            ["artifacts.tenant_id", "artifacts.run_id", "artifacts.id"],
            name="artifacts_parent_artifact_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="artifacts_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="artifacts_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "id",
            name="artifacts_uq_tenant_run_id",
        ),
    )
    op.create_index(
        "artifacts_idx_tenant_run_created",
        "artifacts",
        ["tenant_id", "run_id", "created_at"],
    )
    op.create_index(
        "artifacts_idx_tenant_run_kind",
        "artifacts",
        ["tenant_id", "run_id", "kind"],
    )
    op.create_index(
        "artifacts_idx_tenant_content_hash",
        "artifacts",
        ["tenant_id", "content_hash"],
    )
    op.create_index(
        "artifacts_idx_tenant_parent",
        "artifacts",
        ["tenant_id", "run_id", "parent_artifact_id"],
        postgresql_where=sa.text("parent_artifact_id is not null"),
    )

    op.create_table(
        "context_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt_pack_version", sa.Text(), nullable=False),
        sa.Column("prompt_pack_lock", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("policy_pack_lock", sa.Text(), nullable=False),
        sa.Column("repo_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tool_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_set_hash", sa.Text(), nullable=False),
        sa.Column(
            "provider_continuation_ref",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "provider_request_fingerprint",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("snapshot_kind", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "snapshot_kind in ('input','pre_tool','post_tool','resume','final')",
            name="context_snapshots_ck_snapshot_kind",
        ),
        sa.CheckConstraint(
            "prompt_pack_lock ~ '^[0-9a-f]{64}$'",
            name="context_snapshots_ck_prompt_pack_lock_sha256_hex",
        ),
        sa.CheckConstraint(
            "policy_pack_lock ~ '^[0-9a-f]{64}$'",
            name="context_snapshots_ck_policy_pack_lock_sha256_hex",
        ),
        sa.CheckConstraint(
            "evidence_set_hash ~ '^[0-9a-f]{64}$'",
            name="context_snapshots_ck_evidence_set_hash_sha256_hex",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(repo_state) = 'object'",
            name="context_snapshots_ck_repo_state_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(tool_manifest) = 'object'",
            name="context_snapshots_ck_tool_manifest_object",
        ),
        sa.CheckConstraint(
            "provider_continuation_ref is null "
            "or jsonb_typeof(provider_continuation_ref) = 'object'",
            name="context_snapshots_ck_provider_continuation_ref_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(provider_request_fingerprint) = 'object'",
            name="context_snapshots_ck_provider_request_fingerprint_object",
        ),
        sa.CheckConstraint(
            "provider_continuation_ref is null "
            "or coalesce(provider_continuation_ref->>'exportable' = 'false', false)",
            name="context_snapshots_ck_provider_continuation_ref_exportable_false",
        ),
        sa.CheckConstraint(
            "not jsonb_path_exists(repo_state, "
            f"{_prohibited_payload_keys_jsonpath()}::jsonpath) and "
            "not jsonb_path_exists(tool_manifest, "
            f"{_prohibited_payload_keys_jsonpath()}::jsonpath) and "
            "(provider_continuation_ref is null or not jsonb_path_exists("
            "provider_continuation_ref, "
            f"{_prohibited_payload_keys_jsonpath()}::jsonpath)) and "
            "not jsonb_path_exists(provider_request_fingerprint, "
            f"{_prohibited_payload_keys_jsonpath()}::jsonpath)",
            name="context_snapshots_ck_no_prohibited_payload_keys",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="context_snapshots_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name="context_snapshots_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="context_snapshots_pkey"),
        sa.UniqueConstraint("tenant_id", "id", name="context_snapshots_uq_tenant_id"),
    )
    op.create_check_constraint(
        "context_snapshots_ck_repo_state_required",
        "context_snapshots",
        "coalesce(jsonb_typeof(repo_state->'commit_sha') = 'string', false) "
        "and coalesce(length(repo_state->>'commit_sha') > 0, false) "
        "and coalesce(jsonb_typeof(repo_state->'branch') = 'string', false) "
        "and coalesce(length(repo_state->>'branch') > 0, false) "
        "and coalesce(jsonb_typeof(repo_state->'dirty') = 'boolean', false) "
        "and coalesce(jsonb_typeof(repo_state->'diff_hash') = 'string', false)",
    )
    op.create_check_constraint(
        "context_snapshots_ck_tool_manifest_required",
        "context_snapshots",
        "coalesce(jsonb_typeof(tool_manifest->'registry_version') = 'string', false) "
        "and coalesce(length(tool_manifest->>'registry_version') > 0, false) "
        "and coalesce(jsonb_typeof(tool_manifest->'allowlist_hash') = 'string', false) "
        "and coalesce((tool_manifest->>'allowlist_hash') ~ '^[a-f0-9]{64}$', false)",
    )
    op.create_check_constraint(
        "context_snapshots_ck_fingerprint_required",
        "context_snapshots",
        "coalesce("
        "jsonb_typeof(provider_request_fingerprint->'model_resolved') = 'string', "
        "false"
        ") "
        "and coalesce(length(provider_request_fingerprint->>'model_resolved') > 0, false)",
    )
    op.create_check_constraint(
        "context_snapshots_ck_continuation_ref_required",
        "context_snapshots",
        "provider_continuation_ref is null "
        "or ("
        "coalesce(jsonb_typeof(provider_continuation_ref->'provider') = 'string', false) "
        "and coalesce(length(provider_continuation_ref->>'provider') > 0, false) "
        "and coalesce(jsonb_typeof(provider_continuation_ref->'kind') = 'string', false) "
        "and coalesce(length(provider_continuation_ref->>'kind') > 0, false) "
        "and coalesce(jsonb_typeof(provider_continuation_ref->'artifact_ref') = 'string', false) "
        "and coalesce(length(provider_continuation_ref->>'artifact_ref') > 0, false) "
        "and coalesce((provider_continuation_ref->>'sha256') ~ '^[a-f0-9]{64}$', false) "
        "and coalesce(jsonb_typeof(provider_continuation_ref->'expires_at') = 'string', false) "
        "and coalesce(provider_continuation_ref->>'exportable' = 'false', false)"
        ")",
    )
    op.create_index(
        "context_snapshots_idx_tenant_run_created",
        "context_snapshots",
        ["tenant_id", "run_id", "created_at"],
    )
    op.create_index(
        "context_snapshots_idx_tenant_run_kind",
        "context_snapshots",
        ["tenant_id", "run_id", "snapshot_kind"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "context_snapshots_ck_continuation_ref_required",
        "context_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "context_snapshots_ck_fingerprint_required",
        "context_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "context_snapshots_ck_tool_manifest_required",
        "context_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "context_snapshots_ck_repo_state_required",
        "context_snapshots",
        type_="check",
    )
    op.drop_table("context_snapshots")
    op.drop_table("artifacts")

