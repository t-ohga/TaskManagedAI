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
    JsonDict,
    TenantIdMixin,
    rls_ready_metadata,
)

ApiCapabilityTokenStatus = Literal["issued", "expired", "revoked"]

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


class ApiCapabilityToken(TenantIdMixin, Base):
    __tablename__ = "api_capability_tokens"
    __table_args__ = (
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
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="api_capability_tokens_uq_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "token_hash",
            name="api_capability_tokens_uq_tenant_token_hash",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "jti",
            name="api_capability_tokens_uq_tenant_jti",
        ),
        sa.Index(
            "api_capability_tokens_idx_active",
            "tenant_id",
            "actor_id",
            "status",
            "expires_at",
        ),
        sa.Index(
            "api_capability_tokens_idx_project",
            "tenant_id",
            "project_id",
            "status",
            "expires_at",
            postgresql_where=sa.text("project_id is not null"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    token_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    principal_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    device_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    allowed_actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    scope_constraint: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )
    audience: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        default="taskmanagedai-api",
        server_default=sa.text("'taskmanagedai-api'"),
    )
    auth_context_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    request_binding_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[ApiCapabilityTokenStatus] = mapped_column(
        sa.Text,
        nullable=False,
        default="issued",
        server_default=sa.text("'issued'"),
    )
    issued_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    jti: Mapped[str] = mapped_column(sa.Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["ApiCapabilityToken", "ApiCapabilityTokenStatus"]
