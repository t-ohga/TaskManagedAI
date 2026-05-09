from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, TenantIdMixin
from backend.app.domain.agent_runtime.snapshot_kind import ALL_SNAPSHOT_KINDS, SnapshotKind

JsonDict = dict[str, Any]

CONTEXT_SNAPSHOT_REQUIRED_COLUMNS: tuple[str, ...] = (
    "prompt_pack_version",
    "prompt_pack_lock",
    "policy_version",
    "policy_pack_lock",
    "repo_state",
    "tool_manifest",
    "evidence_set_hash",
    "provider_continuation_ref",
    "provider_request_fingerprint",
    "snapshot_kind",
)

_PROHIBITED_CONTEXT_SNAPSHOT_KEYS: tuple[str, ...] = (
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
)


def _prohibited_context_snapshot_keys_jsonpath() -> str:
    disjunction = " || ".join(
        f'@.key == "{key}"' for key in _PROHIBITED_CONTEXT_SNAPSHOT_KEYS
    )
    return (
        "'strict $.** ? (@.type() == \"object\")."
        f"keyvalue() ? ({disjunction})'"
    )


def _snapshot_kind_check_values() -> str:
    return ",".join(f"'{kind}'" for kind in ALL_SNAPSHOT_KINDS)


class ContextSnapshot(TenantIdMixin, Base):
    """Immutable AgentRun reproducibility snapshot."""

    __tablename__ = "context_snapshots"
    __table_args__ = (
        sa.CheckConstraint(
            f"snapshot_kind in ({_snapshot_kind_check_values()})",
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
            f"{_prohibited_context_snapshot_keys_jsonpath()}::jsonpath) and "
            "not jsonb_path_exists(tool_manifest, "
            f"{_prohibited_context_snapshot_keys_jsonpath()}::jsonpath) and "
            "(provider_continuation_ref is null or not jsonb_path_exists("
            "provider_continuation_ref, "
            f"{_prohibited_context_snapshot_keys_jsonpath()}::jsonpath)) and "
            "not jsonb_path_exists(provider_request_fingerprint, "
            f"{_prohibited_context_snapshot_keys_jsonpath()}::jsonpath)",
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
        sa.UniqueConstraint("tenant_id", "id", name="context_snapshots_uq_tenant_id"),
        sa.Index(
            "context_snapshots_idx_tenant_run_created",
            "tenant_id",
            "run_id",
            "created_at",
        ),
        sa.Index(
            "context_snapshots_idx_tenant_run_kind",
            "tenant_id",
            "run_id",
            "snapshot_kind",
        ),
        {
            "comment": (
                "ContextSnapshot contract: required 10 reproducibility columns, "
                "snapshot_kind enum, exportable=false provider continuation refs, "
                "and no raw secret/provider key/capability token/canary values."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    prompt_pack_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    prompt_pack_lock: Mapped[str] = mapped_column(sa.Text, nullable=False)
    policy_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    policy_pack_lock: Mapped[str] = mapped_column(sa.Text, nullable=False)
    repo_state: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    tool_manifest: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    evidence_set_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provider_continuation_ref: Mapped[JsonDict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    provider_request_fingerprint: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    snapshot_kind: Mapped[SnapshotKind] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


__all__ = [
    "CONTEXT_SNAPSHOT_REQUIRED_COLUMNS",
    "ContextSnapshot",
    "JsonDict",
]

