from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.domain.artifact.data_class import PayloadDataClass
from backend.app.domain.memory.record_kind import MemoryRecordKind
from backend.app.domain.memory.redaction_status import MemoryRedactionStatus
from backend.app.services.input_trust.payload_classifier import PayloadClassificationInput

MemoryRecordTrustLevel = Literal["untrusted_content", "validated_artifact"]
MemoryRetrievalTrustLevel = Literal["untrusted_content"]
MemoryCuratorSourceKind = Literal[
    "completed_run",
    "failed_run",
    "review_finding",
]
MemoryArchiveCandidateKind = Literal[
    "auto_completion",
    "auto_failure",
    "auto_review_finding",
]

DEFAULT_MEMORY_ARCHIVE_CANDIDATE_KINDS: tuple[MemoryArchiveCandidateKind, ...] = (
    "auto_completion",
    "auto_failure",
    "auto_review_finding",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SUMMARY_REF_RE = re.compile(r"^artifact://summary/[A-Za-z0-9._:/@+-]+$")


def _validate_sha256(value: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise ValueError("value must be a lowercase sha256 hex string.")
    return value


def _validate_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware.")
    return value


def _validate_summary_ref(value: str) -> str:
    if not _SUMMARY_REF_RE.fullmatch(value):
        raise ValueError("summary_ref must be an artifact://summary/ reference.")
    return value


class MemoryRecordCreate(BaseModel):
    """Service-layer schema for creating artifact-bound memory metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    record_kind: MemoryRecordKind
    content_artifact_ref: str = Field(..., min_length=1, max_length=512)
    content_hash: str
    data_class: PayloadDataClass
    redaction_status: MemoryRedactionStatus = "redacted"
    sanitizer_version_id: UUID
    source_artifact_id: UUID | None = None
    trust_level: MemoryRecordTrustLevel = "untrusted_content"
    retention_until: datetime

    @field_validator("content_hash")
    @classmethod
    def _content_hash_is_sha256(cls, value: str) -> str:
        return _validate_sha256(value)

    @field_validator("retention_until")
    @classmethod
    def _retention_until_is_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)


class MemoryStoreRequest(BaseModel):
    """Caller-facing memory store input with server-owned fields removed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    run_id: UUID
    record_kind: MemoryRecordKind
    payload: dict[str, Any] = Field(..., min_length=1)
    classification: PayloadClassificationInput = Field(
        default_factory=PayloadClassificationInput
    )
    schema_version: str = Field(default="memory-record.v1", min_length=1, max_length=128)
    retention_until: datetime

    @field_validator("retention_until")
    @classmethod
    def _retention_until_is_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)


class MemoryCuratorRequest(BaseModel):
    """Caller-facing curator input with record kind and artifact metadata server-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    run_id: UUID
    source_artifact_id: UUID
    source_kind: MemoryCuratorSourceKind
    summary_ref: str = Field(..., min_length=1, max_length=512)
    reason_code: str | None = Field(default=None, min_length=1, max_length=128)
    classification: PayloadClassificationInput = Field(
        default_factory=PayloadClassificationInput
    )
    schema_version: str = Field(default="memory-curator.v1", min_length=1, max_length=128)
    retention_until: datetime

    @field_validator("retention_until")
    @classmethod
    def _retention_until_is_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("summary_ref")
    @classmethod
    def _summary_ref_is_ref_only(cls, value: str) -> str:
        return _validate_summary_ref(value)


class MemoryArchivePolicyRequest(BaseModel):
    """Caller-facing archive policy input with manual memory protected by schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    minimum_age_days: int = Field(default=30, ge=1, le=3650)
    max_records: int = Field(default=100, ge=1, le=1000)
    record_kinds: tuple[MemoryArchiveCandidateKind, ...] = Field(
        default=DEFAULT_MEMORY_ARCHIVE_CANDIDATE_KINDS,
        min_length=1,
        max_length=len(DEFAULT_MEMORY_ARCHIVE_CANDIDATE_KINDS),
    )

    @field_validator("record_kinds")
    @classmethod
    def _record_kinds_are_unique(
        cls, value: tuple[MemoryArchiveCandidateKind, ...]
    ) -> tuple[MemoryArchiveCandidateKind, ...]:
        if len(set(value)) != len(value):
            raise ValueError("record_kinds must be unique.")
        return value


class MemoryRetrievalRequest(BaseModel):
    """Caller-facing memory retrieval input with ref-only output metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    retrieval_run_id: UUID
    memory_record_ids: tuple[UUID, ...] = Field(default_factory=tuple, max_length=100)
    record_kinds: tuple[MemoryRecordKind, ...] = Field(default_factory=tuple, max_length=16)
    schema_version: str = Field(default="memory-retrieval.v1", min_length=1, max_length=128)
    limit: int = Field(default=20, ge=1, le=100)


class MemoryRetrievalArtifactCreate(BaseModel):
    """Service-layer schema for recording untrusted memory retrieval metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    memory_record_id: UUID
    retrieval_artifact_ref: str = Field(..., min_length=1, max_length=512)
    retrieval_hash: str
    sanitizer_version_id: UUID
    retrieval_run_id: UUID | None = None
    context_snapshot_id: UUID | None = None
    trust_level: MemoryRetrievalTrustLevel = "untrusted_content"

    @field_validator("retrieval_hash")
    @classmethod
    def _retrieval_hash_is_sha256(cls, value: str) -> str:
        return _validate_sha256(value)


__all__ = [
    "DEFAULT_MEMORY_ARCHIVE_CANDIDATE_KINDS",
    "MemoryArchiveCandidateKind",
    "MemoryArchivePolicyRequest",
    "MemoryCuratorRequest",
    "MemoryCuratorSourceKind",
    "MemoryRecordCreate",
    "MemoryRecordTrustLevel",
    "MemoryRetrievalRequest",
    "MemoryStoreRequest",
    "MemoryRetrievalArtifactCreate",
    "MemoryRetrievalTrustLevel",
]
