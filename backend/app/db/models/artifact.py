from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, TenantIdMixin
from backend.app.domain.artifact.data_class import PayloadDataClass
from backend.app.domain.artifact.trust_level import TrustLevel

JsonDict = dict[str, Any]

ArtifactKind = Literal[
    "plan",
    "patch",
    "evidence",
    "citation",
    "provider_continuation_ref",
    "other",
    "cli_input",
    "cli_stdout",
    "cli_stderr",
    "cli_exit",
    "cli_result_summary",
]

ALL_ARTIFACT_KINDS: tuple[ArtifactKind, ...] = (
    "plan",
    "patch",
    "evidence",
    "citation",
    "provider_continuation_ref",
    "other",
    "cli_input",
    "cli_stdout",
    "cli_stderr",
    "cli_exit",
    "cli_result_summary",
)

_PROHIBITED_ARTIFACT_PAYLOAD_KEYS: tuple[str, ...] = (
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


def _prohibited_artifact_payload_keys_jsonpath() -> str:
    disjunction = " || ".join(
        f'@.key == "{key}"' for key in _PROHIBITED_ARTIFACT_PAYLOAD_KEYS
    )
    return (
        "'strict $.** ? (@.type() == \"object\")."
        f"keyvalue() ? ({disjunction})'"
    )


class Artifact(TenantIdMixin, Base):
    """Immutable AgentRun artifact metadata and redacted JSON body."""

    __tablename__ = "artifacts"
    __table_args__ = (
        sa.CheckConstraint(
            "kind in "
            "('plan','patch','evidence','citation','provider_continuation_ref','other',"
            "'cli_input','cli_stdout','cli_stderr','cli_exit','cli_result_summary')",
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
            "trust_level in ('untrusted_content','validated_artifact','trusted_instruction')",
            name="artifacts_ck_trust_level",
        ),
        sa.CheckConstraint(
            "(kind <> 'provider_continuation_ref') or (exportable = false)",
            name="artifacts_ck_provider_continuation_ref_not_exportable",
        ),
        sa.CheckConstraint(
            "not jsonb_path_exists(content_jsonb, "
            f"{_prohibited_artifact_payload_keys_jsonpath()}::jsonpath)",
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
        sa.UniqueConstraint("tenant_id", "id", name="artifacts_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "id",
            name="artifacts_uq_tenant_run_id",
        ),
        sa.Index("artifacts_idx_tenant_run_created", "tenant_id", "run_id", "created_at"),
        sa.Index("artifacts_idx_tenant_run_kind", "tenant_id", "run_id", "kind"),
        sa.Index("artifacts_idx_tenant_content_hash", "tenant_id", "content_hash"),
        sa.Index(
            "artifacts_idx_tenant_parent",
            "tenant_id",
            "run_id",
            "parent_artifact_id",
            postgresql_where=sa.text("parent_artifact_id is not null"),
        ),
        {
            "comment": (
                "Artifact contract: immutable rows, SHA-256 content_hash, "
                "payload_data_class metadata, exportable flag, and no raw secret, "
                "provider key, capability token, or canary raw values."
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
    kind: Mapped[ArtifactKind] = mapped_column(sa.Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content_jsonb: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    payload_data_class: Mapped[PayloadDataClass] = mapped_column(sa.Text, nullable=False)
    trust_level: Mapped[TrustLevel] = mapped_column(
        sa.Text,
        nullable=False,
        default="untrusted_content",
        server_default=sa.text("'untrusted_content'"),
    )
    exportable: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=True,
        server_default=sa.text("true"),
    )
    parent_artifact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


__all__ = ["ALL_ARTIFACT_KINDS", "Artifact", "ArtifactKind"]

