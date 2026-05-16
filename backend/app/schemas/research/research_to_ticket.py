from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class ResearchToTicketRequest(BaseModel):
    """Server-owned ResearchTask promotion request.

    Callers provide only tenant/project/research task identifiers, the
    promoting actor, and a pre-existing approved ApprovalRequest ID
    (F-PR24-R1-004 P1 adopt: ADR-00003 mandates Approval 4 整合 before
    Ticket mutation; ``approval_request_id`` is the server-trusted
    binding to the Approval workflow decision). ``artifact_hash``,
    ``evidence_set_hash``, and ``ticket_id`` are intentionally absent
    from this schema.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: int = Field(gt=0)
    project_id: UUID
    research_task_id: UUID
    requested_by_actor_id: UUID
    approval_request_id: UUID
    # F-PR24-R4-001 P1 adopt: the Research session that produced the
    # promotion artifact may have invoked a provider call (AI provider
    # generating research_summary). When the approval was issued with a
    # provider_request_fingerprint binding (Approval 4 整合 §3 stale/replay
    # protection), the caller MUST pass the same fingerprint here so the
    # adapter can verify equality. None on both sides indicates a non-
    # provider-driven workflow (e.g., manual research) which is also valid.
    expected_provider_request_fingerprint: str | None = Field(default=None)
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
    approval_request_id: UUID
    artifact_hash: str = Field(pattern=_SHA256_HEX_RE.pattern)
    evidence_set_hash: str = Field(pattern=_SHA256_HEX_RE.pattern)
    claim_count: int = Field(ge=0)
    evidence_item_count: int = Field(ge=0)


__all__ = [
    "ResearchToTicketOutcome",
    "ResearchToTicketRequest",
]
