from __future__ import annotations

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
from backend.app.domain.tool_registry.network_policy import (
    NetworkAccessMode,
    PayloadDataClass,
    ToolAllowedAction,
    ToolAuthMode,
    ToolTransport,
    ToolTrustTier,
)


class ToolRegistry(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "tool_registry"
    __table_args__ = (
        sa.CheckConstraint(
            "transport in ('local','stdio')",
            name="tool_registry_ck_transport",
        ),
        sa.CheckConstraint(
            "auth_mode in ('none','env_ref')",
            name="tool_registry_ck_auth_mode",
        ),
        sa.CheckConstraint(
            "network_access in ('none','allowlist','internet')",
            name="tool_registry_ck_network_access",
        ),
        sa.CheckConstraint(
            "trust_tier in ('official','self_hosted','third_party','experimental')",
            name="tool_registry_ck_trust_tier",
        ),
        sa.CheckConstraint(
            "length(registry_version) > 0",
            name="tool_registry_ck_registry_version_non_empty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_actions) = 'array' "
            "and jsonb_array_length(allowed_actions) > 0 "
            "and not jsonb_path_exists("
            "allowed_actions, '$[*] ? (@.type() != \"string\")'::jsonpath"
            ") "
            "and not jsonb_path_exists("
            "allowed_actions, "
            "'$[*] ? (@ != \"web_fetch\" && @ != \"docs_search\" "
            "&& @ != \"code_grep\" && @ != \"filesystem_read\")'::jsonpath"
            ")",
            name="tool_registry_ck_allowed_actions",
        ),
        sa.CheckConstraint(
            "max_outgoing_data_class in ('public','internal','confidential','pii')",
            name="tool_registry_ck_max_outgoing_data_class",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="tool_registry_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="tool_registry_uq_tenant_id"),
        sa.UniqueConstraint("tenant_id", "tool_key", name="tool_registry_uq_tool_key"),
        sa.Index("tool_registry_idx_tenant_network_access", "tenant_id", "network_access"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    tool_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    transport: Mapped[ToolTransport] = mapped_column(sa.Text, nullable=False)
    auth_mode: Mapped[ToolAuthMode] = mapped_column(sa.Text, nullable=False)
    network_access: Mapped[NetworkAccessMode] = mapped_column(
        sa.Text,
        nullable=False,
        default="none",
        server_default=sa.text("'none'"),
    )
    trust_tier: Mapped[ToolTrustTier] = mapped_column(sa.Text, nullable=False)
    registry_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    allowed_actions: Mapped[list[ToolAllowedAction]] = mapped_column(JSONB, nullable=False)
    max_outgoing_data_class: Mapped[PayloadDataClass] = mapped_column(
        sa.Text,
        nullable=False,
    )
    manifest: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


class ToolNetworkPolicy(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "tool_network_policies"
    __table_args__ = (
        sa.CheckConstraint(
            "jsonb_typeof(domain_allowlist) = 'array'",
            name="tool_network_policies_ck_domain_allowlist_array",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(domain_allowlist) > 0",
            name="tool_network_policies_ck_domain_allowlist_non_empty",
        ),
        sa.CheckConstraint(
            "payload_data_class_max in ('public','internal','confidential','pii')",
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
        sa.UniqueConstraint("tenant_id", "id", name="tool_network_policies_uq_tenant_id"),
        sa.UniqueConstraint("tenant_id", "tool_id", name="tool_network_policies_uq_tool"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    tool_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    domain_allowlist: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    payload_data_class_max: Mapped[PayloadDataClass] = mapped_column(sa.Text, nullable=False)
    provider_required: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=False,
        server_default=sa.text("false"),
    )
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


class ToolVersion(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "tool_versions"
    __table_args__ = (
        sa.CheckConstraint(
            "length(registry_version) > 0",
            name="tool_versions_ck_registry_version_non_empty",
        ),
        sa.CheckConstraint(
            "allowlist_hash ~ '^[a-f0-9]{64}$'",
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
        sa.UniqueConstraint("tenant_id", "id", name="tool_versions_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "tool_id",
            "registry_version",
            name="tool_versions_uq_tool_registry_version",
        ),
        sa.Index(
            "tool_versions_idx_tenant_registry_version",
            "tenant_id",
            "registry_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    tool_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    registry_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    allowlist_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    manifest: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["ToolNetworkPolicy", "ToolRegistry", "ToolVersion"]
