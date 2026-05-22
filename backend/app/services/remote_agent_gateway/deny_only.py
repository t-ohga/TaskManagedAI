from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.audit_event import AuditEvent
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

REMOTE_AGENT_DISPATCH_DENIED_EVENT_TYPE = "remote_agent_dispatch_denied"
REMOTE_AGENT_DENY_REASON = "p0_1_stub"

RemoteAgentDispatchDecisionValue = Literal["deny"]


class RemoteAgentGatewayError(ValueError):
    """Remote agent gateway guard violation."""


@dataclass(frozen=True)
class RemoteAgentDispatchRequest:
    tenant_id: int
    actor_id: UUID
    role_id: str
    requested_remote_role: str
    capability_class: str
    project_id: UUID | None = None
    run_id: UUID | None = None
    correlation_id: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class RemoteAgentDispatchDecision:
    decision: RemoteAgentDispatchDecisionValue
    reason_code: str
    audit_event_id: UUID


class RemoteAgentGateway:
    """P0.1 deny-only remote agent gateway stub.

    This is intentionally not an adapter. It records an audit event and denies
    every dispatch request until ADR-00013 full remote integration is accepted.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def deny_dispatch(
        self,
        request: RemoteAgentDispatchRequest,
    ) -> RemoteAgentDispatchDecision:
        await _ensure_tenant_context(self.session, request.tenant_id)
        _validate_request(request)
        payload = _build_denied_payload(request)
        assert_no_raw_secret(payload)

        audit_event = AuditEvent(
            tenant_id=request.tenant_id,
            event_type=REMOTE_AGENT_DISPATCH_DENIED_EVENT_TYPE,
            event_payload=payload,
            actor_id=request.actor_id,
            principal_id=None,
            correlation_id=request.correlation_id,
            trace_id=request.trace_id,
        )
        self.session.add(audit_event)
        await self.session.flush()

        return RemoteAgentDispatchDecision(
            decision="deny",
            reason_code=REMOTE_AGENT_DENY_REASON,
            audit_event_id=audit_event.id,
        )


async def _ensure_tenant_context(session: AsyncSession, tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise RemoteAgentGatewayError("tenant_id must be a positive integer.")
    current = await get_tenant_context(session)
    if current is None:
        await set_tenant_context(session, tenant_id)
    await assert_tenant_context(session, tenant_id)


def _validate_request(request: RemoteAgentDispatchRequest) -> None:
    for field_name in ("role_id", "requested_remote_role", "capability_class"):
        value = getattr(request, field_name)
        if not isinstance(value, str) or not value.strip():
            raise RemoteAgentGatewayError(f"{field_name} must be a non-empty string.")


def _build_denied_payload(request: RemoteAgentDispatchRequest) -> dict[str, object]:
    return {
        "reason_code": REMOTE_AGENT_DENY_REASON,
        "gateway_kind": "remote_agent",
        "decision": "deny",
        "tenant_id": request.tenant_id,
        "actor_id": str(request.actor_id),
        "project_id": str(request.project_id) if request.project_id is not None else None,
        "run_id": str(request.run_id) if request.run_id is not None else None,
        "role_id": request.role_id,
        "requested_remote_role": request.requested_remote_role,
        "capability_class": request.capability_class,
        "payload_data_class": "internal",
        "raw_secret_check_passed": True,
    }


__all__ = [
    "REMOTE_AGENT_DENY_REASON",
    "REMOTE_AGENT_DISPATCH_DENIED_EVENT_TYPE",
    "RemoteAgentDispatchDecision",
    "RemoteAgentDispatchRequest",
    "RemoteAgentGateway",
    "RemoteAgentGatewayError",
]
