from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class ResearchToTicketRequest(BaseModel):
    """Server-owned ResearchTask promotion request.

    Callers provide only tenant/project/research task identifiers and the
    promoting actor. ``artifact_hash``, ``evidence_set_hash``, and ``ticket_id``
    are intentionally absent from this schema.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: int = Field(gt=0)
    project_id: UUID
    research_task_id: UUID
    requested_by_actor_id: UUID
    ticket_title_override: str | None = Field(default=None, max_length=2000)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id_must_be_positive_int(cls, value: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError("tenant_id must be a positive integer.")
        return value

    @field_validator("ticket_title_override")
    @classmethod
    def _normalize_ticket_title_override(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = unicodedata.normalize("NFC", value).strip()
        if not normalized:
            raise ValueError("ticket_title_override must not be blank.")
        return normalized


class ResearchToTicketOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticket_id: UUID
    artifact_hash: str = Field(pattern=_SHA256_HEX_RE.pattern)
    evidence_set_hash: str = Field(pattern=_SHA256_HEX_RE.pattern)
    claim_count: int = Field(ge=0)
    evidence_item_count: int = Field(ge=0)


__all__ = [
    "ResearchToTicketOutcome",
    "ResearchToTicketRequest",
]
