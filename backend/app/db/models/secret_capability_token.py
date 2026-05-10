from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import (
    Base,
    CreatedAtMixin,
    JsonDict,
    TenantIdMixin,
    rls_ready_metadata,
)

SecretCapabilityTokenStatus = Literal["issued", "redeeming", "used", "expired", "revoked"]

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


class SecretCapabilityToken(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "secret_capability_tokens"
    __table_args__ = (
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
        sa.Index(
            "secret_capability_tokens_idx_expires_at",
            "tenant_id",
            "expires_at",
            postgresql_where=sa.text("status = 'issued'"),
        ),
        sa.Index(
            "secret_capability_tokens_idx_issued_status",
            "tenant_id",
            "secret_ref_id",
            "status",
            postgresql_where=sa.text("status = 'issued'"),
        ),
        sa.Index(
            "secret_capability_tokens_idx_issued_actor",
            "tenant_id",
            "issued_to_actor_id",
        ),
        sa.Index(
            "secret_capability_tokens_idx_issued_run",
            "tenant_id",
            "issued_run_id",
            postgresql_where=sa.text("issued_run_id is not null"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    secret_ref_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    allowed_operations: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sa.text("'[]'::jsonb"),
    )
    scope_constraint: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )
    issued_to_actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    issued_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    expected_request_fingerprint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    status: Mapped[SecretCapabilityTokenStatus] = mapped_column(sa.Text, nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["SecretCapabilityToken", "SecretCapabilityTokenStatus"]

