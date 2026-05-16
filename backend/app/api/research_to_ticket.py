"""Research-to-Ticket promotion REST API (Sprint 10 BL-0118).

Single endpoint that creates a ``research_promotion`` artifact bound
to the supplied AgentRun. The artifact carries the server-computed
``evidence_set_hash`` for the claim/evidence set so a downstream Ticket
creation flow can attach it without recomputing.

POST /api/v1/projects/{project_id}/research-tasks/{research_task_id}/promote
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.services.research.research_to_ticket_adapter import (
    ResearchToTicketError,
    promote_research_to_ticket,
)

# F-PR25-R4-005 fix (Codex R4 P1): the request's X-Trace-Id / X-
# Correlation-Id headers land directly in audit_events.trace_id /
# correlation_id. The shared raw-secret scanner only inspects JSON
# payload bodies, so a copy-pasted OpenAI key or canary in either
# header would become durable audit data. Narrow the accepted format
# to OpenTelemetry / W3C Trace Context (16-32 hex chars) or canonical
# UUID, mirroring backend/app/api/claims.py::_TRACE_ID_RE.
_TRACE_ID_RE = re.compile(
    r"^(?:[0-9a-f]{16}|[0-9a-f]{32}|"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


def _sanitize_trace_header(value: str | None, *, header_name: str) -> str | None:
    """Return ``value`` if it matches the trace ID grammar, else raise 400.

    Returning ``None`` for unset headers is allowed so callers without
    distributed tracing still produce well-formed audit events.
    """

    if value is None:
        return None
    normalized = value.strip().lower()
    if not _TRACE_ID_RE.match(normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{header_name} must be OpenTelemetry 16/32-char hex "
                f"or canonical UUID (got {len(value)} chars matching neither)."
            ),
        )
    return normalized

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/research-tasks/{research_task_id}",
    tags=["research-to-ticket"],
)


class ResearchToTicketPromoteRequest(BaseModel):
    """Caller payload. Server owns ``content_hash`` /
    ``evidence_set_hash`` / IDs / timestamps.

    F-PR25-R3-005 fix (Codex R3 P2): ``extra="forbid"`` so a caller
    sending documented-but-unimplemented fields (e.g.
    ``target_ticket_action``, ``existing_ticket_id``) or any server-
    owned field receives a structured 422 instead of having the field
    silently dropped while the endpoint returns 201.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    summary: str = Field(min_length=1, max_length=4000)
    claim_ids: tuple[UUID, ...] = Field(default_factory=tuple)
    evidence_item_ids: tuple[UUID, ...] = Field(default_factory=tuple)
    parent_artifact_id: UUID | None = None
    # F-PR25-R8-003 fix Stage 1: caller-supplied data classification
    # (validated against Provider Compliance Matrix enum). Stage 2
    # (server-side automatic classification) lands in SP-011 / DD-04
    # classifier integration.
    payload_data_class: str = Field(
        default="internal",
        pattern=r"^(public|internal|confidential|pii)$",
    )
    # F-PR25-R3-002 fix (Codex R3 P1): the Research-to-Ticket flow is
    # ``task_write`` action class per ADR-00003 and requires Approval
    # binding before promoting evidence to a Ticket-creation seed.
    # Full Approval integration (4-binding check against an approved
    # ApprovalRequest row) is deferred to SP-010 batch 4 / SP-008; in
    # the meantime, the endpoint refuses to commit without an
    # ``approval_request_id`` so callers cannot seed Ticket work from
    # unapproved Research output. The repository-level check is
    # documented as Stage 1 (presence guard); Stage 2 (verify the
    # ApprovalRequest is approved + binds the same evidence_set_hash)
    # lands in batch 4 alongside the rest of the Approval 4 integration.
    approval_request_id: UUID


class ResearchToTicketPromoteResponse(BaseModel):
    """Returns the server-computed identity of the promotion artifact +
    the evidence_set_hash that downstream Ticket creation should
    attach to its ContextSnapshot."""

    artifact_id: UUID
    run_id: UUID
    content_hash: str
    evidence_set_hash: str
    payload: dict[str, Any]


@router.post(
    "/promote",
    response_model=ResearchToTicketPromoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def promote(
    project_id: UUID,
    research_task_id: UUID,
    payload: ResearchToTicketPromoteRequest,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: int = Depends(get_tenant_id),
    actor_id: UUID = Depends(get_current_actor_id),
    x_trace_id: Annotated[str | None, Header(alias="X-Trace-Id")] = None,
    x_correlation_id: Annotated[
        str | None, Header(alias="X-Correlation-Id")
    ] = None,
) -> ResearchToTicketPromoteResponse:
    try:
        view = await promote_research_to_ticket(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            research_task_id=research_task_id,
            claim_ids=payload.claim_ids,
            evidence_item_ids=payload.evidence_item_ids,
            run_id=payload.run_id,
            summary=payload.summary,
            parent_artifact_id=payload.parent_artifact_id,
            approval_request_id=payload.approval_request_id,
            payload_data_class=payload.payload_data_class,
        )
    except ResearchToTicketError as exc:
        if exc.reason_code in (
            "research_task_not_in_project",
            "agent_run_not_found",
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        if exc.reason_code in (
            "approval_request_required",
            "approval_request_not_found",
            "approval_request_tenant_mismatch",
            "approval_request_run_mismatch",
            "approval_request_action_class_mismatch",
            "approval_request_not_approved",
        ):
            # F-PR25-R3-002 + F-PR25-R8-001 fix: Approval boundary
            # violation. 403 (vs 422 generic) so the client
            # distinguishes "missing/invalid authorisation" from
            # "request body invalid".
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except IntegrityError as exc:
        # F-PR25-R2-004 fix (Codex R2 P2): a stale or different-run
        # ``parent_artifact_id`` trips the composite
        # ``artifacts_parent_artifact_fkey`` during flush. The handler
        # used to surface this as a 500; map to a structured 4xx.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"promotion integrity violation: {exc.orig}",
        ) from exc

    # F-PR25-R4-005 fix (Codex R4 P1): sanitize the trace headers
    # before they reach ``audit_events.trace_id`` /
    # ``correlation_id``. Mirrors backend/app/api/claims.py.
    safe_trace_id = _sanitize_trace_header(
        x_trace_id, header_name="X-Trace-Id"
    )
    safe_correlation_id = _sanitize_trace_header(
        x_correlation_id, header_name="X-Correlation-Id"
    )

    # F-PR25-R4-006 + F-PR25-R5-007 fix: the documented "all" paths
    # leave ``payload.claim_ids`` / ``payload.evidence_item_ids``
    # empty; the adapter resolves the actual sets into
    # ``content_jsonb`` so the promotion artifact freezes the scope.
    # Use the resolved counts for the audit record so consumers do
    # not see ``0`` for full-scope promotions.
    resolved_claim_count = int(
        view.artifact.content_jsonb.get("claim_count")
        or len(payload.claim_ids)
    )
    resolved_evidence_item_count = int(
        view.artifact.content_jsonb.get("evidence_item_count")
        or len(payload.evidence_item_ids)
    )

    # F-PR25-R2-005 + F-PR25-R3-001 + F-PR25-R4-001 fix: append the
    # ``research_to_ticket_promoted`` audit event so the human/API
    # caller is durably linked to the evidence set seeding downstream
    # ticket work (SP-010 audit contract §line 175-183). R4 fix
    # mirrors tenant_id / actor_id / trace_id / correlation_id into
    # the JSON payload too — the audit table columns capture them but
    # consumers that export only ``event_payload`` (existing claim /
    # evidence event consumers do this) cannot otherwise correlate the
    # promotion back to the request.
    audit = AuditEventRepository(session)
    await audit.append(
        tenant_id=tenant_id,
        actor_id=actor_id,
        event_type="research_to_ticket_promoted",
        trace_id=safe_trace_id,
        correlation_id=safe_correlation_id,
        payload={
            "tenant_id": tenant_id,
            "actor_id": str(actor_id),
            "trace_id": safe_trace_id,
            "correlation_id": safe_correlation_id,
            "project_id": str(project_id),
            "research_task_id": str(research_task_id),
            "run_id": str(view.artifact.run_id),
            "artifact_id": str(view.artifact.id),
            "approval_request_id": str(payload.approval_request_id),
            "evidence_set_hash": view.evidence_set_hash,
            "content_hash": view.artifact.content_hash,
            "claim_id_count": resolved_claim_count,
            "evidence_item_id_count": resolved_evidence_item_count,
            # ISO-8601 server timestamp so consumers do not need to
            # rely on the audit_event row's created_at for ordering
            # within a single transaction.
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    # F-PR25-R2-001 fix (Codex R2 P1): the service only flushes; the
    # ``get_db_session`` dependency does not auto-commit on teardown,
    # so a successful 201 response would otherwise roll back the
    # artifact + audit event. Commit explicitly before returning.
    await session.commit()

    return ResearchToTicketPromoteResponse(
        artifact_id=view.artifact.id,
        run_id=view.artifact.run_id,
        content_hash=view.artifact.content_hash,
        evidence_set_hash=view.evidence_set_hash,
        payload=dict(view.artifact.content_jsonb),
    )


__all__ = ["router"]
