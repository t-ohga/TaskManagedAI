from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import (
    Base,
    CreatedAtMixin,
    JsonDict,
    TenantIdMixin,
    UpdatedAtMixin,
    rls_ready_metadata,
)

SecretRefScope = Literal["p0", "workspace", "project", "repo", "agent_run", "provider"]
SecretRefStatus = Literal["pending", "active", "deprecated", "revoked"]

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


class SecretRef(TenantIdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "secret_refs"
    __table_args__ = (
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
        sa.Index(
            "secret_refs_one_active_per_name",
            "tenant_id",
            "scope",
            "name",
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
        ),
        sa.Index(
            "secret_refs_one_pending_per_name",
            "tenant_id",
            "scope",
            "name",
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        ),
        sa.Index("secret_refs_idx_status", "tenant_id", "status"),
        sa.Index("secret_refs_idx_scope_name", "tenant_id", "scope", "name"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    secret_uri: Mapped[str] = mapped_column(sa.Text, nullable=False)
    scope: Mapped[SecretRefScope] = mapped_column(sa.Text, nullable=False)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[SecretRefStatus] = mapped_column(sa.Text, nullable=False)
    runner_injectable: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=False,
        server_default=sa.text("false"),
    )
    allowed_consumers: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sa.text("'[]'::jsonb"),
    )
    allowed_operations: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sa.text("'[]'::jsonb"),
    )
    owner_actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    rotated_from_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )
    deprecated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )


__all__ = ["SecretRef", "SecretRefScope", "SecretRefStatus"]

