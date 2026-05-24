from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, TenantIdMixin
from backend.app.domain.artifact.data_class import PayloadDataClass
from backend.app.domain.memory.record_kind import ALL_MEMORY_RECORD_KINDS, MemoryRecordKind
from backend.app.domain.memory.redaction_status import (
    ALL_MEMORY_REDACTION_STATUSES,
    MemoryRedactionStatus,
)

MemoryRecordTrustLevel = Literal["untrusted_content", "validated_artifact"]
MemoryRetrievalTrustLevel = Literal["untrusted_content"]


def _quoted(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


class MemoryRecord(TenantIdMixin, Base):
    """Project-scoped memory metadata with artifact-bound redacted content."""

    __tablename__ = "memory_records"
    __table_args__ = (
        sa.CheckConstraint(
            f"record_kind in ({_quoted(ALL_MEMORY_RECORD_KINDS)})",
            name="memory_records_ck_record_kind",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="memory_records_ck_content_hash_sha256_hex",
        ),
        sa.CheckConstraint(
            "data_class in ('public','internal','confidential','pii')",
            name="memory_records_ck_data_class",
        ),
        sa.CheckConstraint(
            f"redaction_status in ({_quoted(ALL_MEMORY_REDACTION_STATUSES)})",
            name="memory_records_ck_redaction_status",
        ),
        sa.CheckConstraint(
            "trust_level in ('untrusted_content','validated_artifact')",
            name="memory_records_ck_trust_level_no_trusted_instruction",
        ),
        sa.CheckConstraint(
            "length(content_artifact_ref) > 0",
            name="memory_records_ck_content_artifact_ref_non_empty",
        ),
        sa.CheckConstraint(
            "retention_until > created_at",
            name="memory_records_ck_retention_after_created",
        ),
        sa.CheckConstraint(
            "archived_at is null or archived_at >= created_at",
            name="memory_records_ck_archived_after_created",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="memory_records_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="memory_records_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sanitizer_version_id"],
            ["sanitizer_policy_versions.tenant_id", "sanitizer_policy_versions.id"],
            name="memory_records_sanitizer_policy_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "source_artifact_id"],
            ["artifacts.tenant_id", "artifacts.project_id", "artifacts.id"],
            name="memory_records_source_artifact_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="memory_records_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="memory_records_uq_tenant_project_id",
        ),
        sa.Index(
            "memory_records_idx_tenant_project_kind_created",
            "tenant_id",
            "project_id",
            "record_kind",
            "created_at",
        ),
        sa.Index(
            "memory_records_idx_active_retention",
            "tenant_id",
            "project_id",
            "retention_until",
            postgresql_where=sa.text("archived_at is null"),
        ),
        {
            "comment": (
                "Project-scoped memory metadata. Redacted content lives in artifact "
                "storage and is referenced by content_artifact_ref + content_hash."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    record_kind: Mapped[MemoryRecordKind] = mapped_column(sa.Text, nullable=False)
    content_artifact_ref: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    data_class: Mapped[PayloadDataClass] = mapped_column(sa.Text, nullable=False)
    redaction_status: Mapped[MemoryRedactionStatus] = mapped_column(
        sa.Text,
        nullable=False,
        default="redacted",
        server_default=sa.text("'redacted'"),
    )
    sanitizer_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_artifact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    trust_level: Mapped[MemoryRecordTrustLevel] = mapped_column(
        sa.Text,
        nullable=False,
        default="untrusted_content",
        server_default=sa.text("'untrusted_content'"),
    )
    retention_until: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


class MemoryRetrievalArtifact(TenantIdMixin, Base):
    """Immutable retrieval event metadata bound to memory record and artifact refs."""

    __tablename__ = "memory_retrieval_artifacts"
    __table_args__ = (
        sa.CheckConstraint(
            "retrieval_hash ~ '^[0-9a-f]{64}$'",
            name="memory_retrieval_artifacts_ck_retrieval_hash_sha256_hex",
        ),
        sa.CheckConstraint(
            "trust_level = 'untrusted_content'",
            name="memory_retrieval_artifacts_ck_trust_level_untrusted",
        ),
        sa.CheckConstraint(
            "length(retrieval_artifact_ref) > 0",
            name="memory_retrieval_artifacts_ck_retrieval_artifact_ref_non_empty",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="memory_retrieval_artifacts_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="memory_retrieval_artifacts_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "memory_record_id"],
            ["memory_records.tenant_id", "memory_records.project_id", "memory_records.id"],
            name="memory_retrieval_artifacts_memory_record_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sanitizer_version_id"],
            ["sanitizer_policy_versions.tenant_id", "sanitizer_policy_versions.id"],
            name="memory_retrieval_artifacts_sanitizer_policy_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "retrieval_run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="memory_retrieval_artifacts_retrieval_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "context_snapshot_id"],
            ["context_snapshots.tenant_id", "context_snapshots.id"],
            name="memory_retrieval_artifacts_context_snapshot_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="memory_retrieval_artifacts_uq_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="memory_retrieval_artifacts_uq_tenant_project_id",
        ),
        sa.Index(
            "memory_retrieval_artifacts_idx_tenant_project_record_created",
            "tenant_id",
            "project_id",
            "memory_record_id",
            "created_at",
        ),
        sa.Index(
            "memory_retrieval_artifacts_idx_retrieval_run",
            "tenant_id",
            "project_id",
            "retrieval_run_id",
            postgresql_where=sa.text("retrieval_run_id is not null"),
        ),
        {
            "comment": (
                "Memory retrieval metadata remains untrusted_content and points to "
                "artifact-bound snippets rather than raw prompt text."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    memory_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    retrieval_artifact_ref: Mapped[str] = mapped_column(sa.Text, nullable=False)
    retrieval_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    sanitizer_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    retrieval_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    context_snapshot_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    trust_level: Mapped[MemoryRetrievalTrustLevel] = mapped_column(
        sa.Text,
        nullable=False,
        default="untrusted_content",
        server_default=sa.text("'untrusted_content'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


__all__ = [
    "MemoryRecord",
    "MemoryRecordTrustLevel",
    "MemoryRetrievalArtifact",
    "MemoryRetrievalTrustLevel",
]
