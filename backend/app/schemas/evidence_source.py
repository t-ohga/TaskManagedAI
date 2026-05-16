from __future__ import annotations

import re
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

# F-PR26-R2-002 P1 adopt: parity with the frontend SECRETISH_PATTERN
# regex (`frontend/lib/api/research.ts`). Embedded tokens inside the
# host or path (e.g., ``/sk-AbCdEf...``, ``/api_key/...``,
# ``capability_token``) must be redacted at the API boundary so the
# raw value never reaches non-UI clients or HTTP logs. Keep both
# server and client redaction in sync.
_SECRETISH_PATTERN = re.compile(
    r"(secret://|secret_ref|capability[_-]?token|api[_-]?key|"
    r"authorization|bearer|sk-[A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)


def _redact_canonical_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[redacted]"
    if parsed.scheme not in _SAFE_URL_PROTOCOLS:
        return "[redacted]"
    if not parsed.hostname:
        return "[redacted]"
    # F-PR26-R2-001 P2 adopt: parsed.port raises ValueError on
    # malformed / out-of-range ports (e.g., ``:99999``). The DB only
    # enforces length/hash, not URL port validity, so listing or
    # fetching such a source would 500 on API serialization. Fail-
    # closed to "[redacted]" instead.
    try:
        port = parsed.port
    except ValueError:
        return "[redacted]"
    host_part = parsed.hostname
    if port is not None:
        host_part = f"{host_part}:{port}"
    # F-PR26-R2-002 P1 adopt: also reject secret-shaped host/path.
    if _SECRETISH_PATTERN.search(f"{host_part}{parsed.path}"):
        return "[redacted]"
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
