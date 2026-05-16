from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _safe_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("metadata must be a JSON object.")
    return {"rls_ready": value.get("rls_ready") is True}


# F-PR26-R1-003 P2 adopt: redact embedded credentials, query strings,
# and fragments from canonical_url BEFORE serializing through the API.
# The stored ``evidence_sources.canonical_url`` column may carry
# basic-auth creds (``user:pass@host``), presigned-style ``?signature=``
# query params, or fragment tokens from imported research. Stripping at
# the API boundary prevents those raw values from reaching the network
# log / non-UI clients / browser DevTools.
_SAFE_URL_PROTOCOLS = frozenset({"http", "https"})


def _redact_canonical_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[redacted]"
    if parsed.scheme not in _SAFE_URL_PROTOCOLS:
        return "[redacted]"
    if not parsed.hostname:
        return "[redacted]"
    host_part = parsed.hostname
    if parsed.port is not None:
        host_part = f"{host_part}:{parsed.port}"
    return urlunsplit((parsed.scheme, host_part, parsed.path, "", ""))


class EvidenceSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, frozen=True)

    id: UUID
    tenant_id: int
    canonical_url: str
    content_hash: str
    retrieved_at: datetime
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(validation_alias="metadata_")

    @field_validator("canonical_url", mode="before")
    @classmethod
    def _canonical_url_must_be_redacted(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("canonical_url must be a string.")
        return _redact_canonical_url(value)

    @field_validator("metadata", mode="before")
    @classmethod
    def _metadata_must_be_safe_subset(cls, value: object) -> dict[str, Any]:
        return _safe_metadata(value)


class EvidenceSourceListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[EvidenceSourceRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


__all__ = [
    "EvidenceSourceListResponse",
    "EvidenceSourceRead",
]
