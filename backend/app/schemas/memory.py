from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.domain.artifact.data_class import PayloadDataClass
from backend.app.domain.memory.record_kind import MemoryRecordKind
from backend.app.domain.memory.redaction_status import MemoryRedactionStatus

MemoryRecordTrustLevel = Literal["untrusted_content", "validated_artifact"]
MemoryRetrievalTrustLevel = Literal["untrusted_content"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_sha256(value: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise ValueError("value must be a lowercase sha256 hex string.")
    return value


def _validate_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware.")
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
    "MemoryRecordCreate",
    "MemoryRecordTrustLevel",
    "MemoryRetrievalArtifactCreate",
    "MemoryRetrievalTrustLevel",
]
