from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

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

    # F-PR24-R5-003 P2 adopt: ``StrictInt`` rejects Pydantic's default lax
    # coercion (e.g., bool ``True`` -> int ``1``). Without strict parsing
    # a JSON ``tenant_id: true`` would silently promote under tenant 1,
    # bypassing the after-validator ``isinstance(value, bool)`` guard
    # since by that point the value is already ``int``.
    tenant_id: StrictInt = Field(gt=0)
    project_id: UUID
    research_task_id: UUID
    requested_by_actor_id: UUID
    approval_request_id: UUID
    # F-PR24-R7-001 P1 adopt: ``expected_provider_request_fingerprint`` was
    # removed from this schema. server-owned-boundary §1/§2 forbid
    # caller-supplied fingerprint paths. The correct server-side derivation
    # is to navigate ``research_task -> source AgentRun -> ContextSnapshot.
    # provider_request_fingerprint`` and compare against
    # ``ApprovalRequest.provider_request_fingerprint``, but ResearchTask
    # does not yet carry the source ``agent_run_id`` column in the batch 3
    # DB schema. The pragmatic batch 3 contract is therefore:
    #     ApprovalRequest.provider_request_fingerprint MUST be NULL
    # (Research-to-Ticket promotion in batch 3 is not provider-bound).
    # Sprint 11 BL-0126 adds the ResearchTask.agent_run_id column and
    # corresponding server-side fingerprint derivation to enable
    # provider-bound research workflows under server-owned-boundary §3.
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
