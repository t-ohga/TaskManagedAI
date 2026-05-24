from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.models.policy_decision import PolicyDecision
from backend.app.domain.agent_runtime.event_type import AgentRunEventType
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.agent_run_event import AgentRunEventRepository
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.policy_decision import PolicyDecisionRepository
from backend.app.services.policy.autonomy_policy_engine import AutonomyPolicyEngineDecision

AUTONOMY_POLICY_AUDIT_EVENT_TYPE = "policy_decision_created"
AUTONOMY_POLICY_AGENT_EVENT_TYPE: AgentRunEventType = "policy_linted"

_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class AutonomyPolicyTracePayloads:
    policy_decision_payload: dict[str, Any]
    audit_event_type: str
    audit_payload: dict[str, Any]
    agent_event_type: AgentRunEventType
    agent_event_payload: dict[str, Any]


@dataclass(frozen=True)
class AutonomyPolicyTraceRecord:
    policy_decision: PolicyDecision
    audit_event: AuditEvent
    agent_event: AgentRunEvent


async def append_autonomy_policy_trace(
    session: AsyncSession,
    *,
    tenant_id: int,
    decision: AutonomyPolicyEngineDecision,
    actor_id: UUID,
    run_id: UUID,
    policy_version: str,
    input_hash: str,
    approval_request_id: UUID | None = None,
    required_review_artifact_id: UUID | None = None,
    principal_id: UUID | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    agent_event_idempotency_key: str | None = None,
) -> AutonomyPolicyTraceRecord:
    """Append policy_decisions + audit + AgentRunEvent for one autonomy decision.

    The trace API deliberately accepts only a precomputed ``input_hash``. Raw
    prompt, raw provider payload, raw secret, and capability token values do not
    exist in the signature and cannot be mirrored into trace rows by accident.
    """

    payloads = build_autonomy_policy_trace_payloads(
        decision=decision,
        actor_id=actor_id,
        run_id=run_id,
        policy_version=policy_version,
        input_hash=input_hash,
        approval_request_id=approval_request_id,
        required_review_artifact_id=required_review_artifact_id,
    )
    policy_decision = await PolicyDecisionRepository(session).append(
        tenant_id,
        **payloads.policy_decision_payload,
    )

    event_payloads = build_autonomy_policy_trace_payloads(
        decision=decision,
        actor_id=actor_id,
        run_id=run_id,
        policy_version=policy_version,
        input_hash=input_hash,
        approval_request_id=approval_request_id,
        required_review_artifact_id=required_review_artifact_id,
        policy_decision_id=policy_decision.id,
    )
    audit_event = await AuditEventRepository(session).append(
        tenant_id=tenant_id,
        event_type=event_payloads.audit_event_type,
        payload=event_payloads.audit_payload,
        actor_id=actor_id,
        principal_id=principal_id,
        correlation_id=correlation_id,
        trace_id=trace_id,
    )
    agent_event = await AgentRunEventRepository(session).append_event(
        tenant_id=tenant_id,
        run_id=run_id,
        event_type=event_payloads.agent_event_type,
        event_payload=event_payloads.agent_event_payload,
        actor_id=actor_id,
        idempotency_key=agent_event_idempotency_key,
    )
    return AutonomyPolicyTraceRecord(
        policy_decision=policy_decision,
        audit_event=audit_event,
        agent_event=agent_event,
    )


def build_autonomy_policy_trace_payloads(
    *,
    decision: AutonomyPolicyEngineDecision,
    actor_id: UUID,
    run_id: UUID,
    policy_version: str,
    input_hash: str,
    approval_request_id: UUID | None = None,
    required_review_artifact_id: UUID | None = None,
    policy_decision_id: UUID | None = None,
) -> AutonomyPolicyTracePayloads:
    _validate_policy_version(policy_version)
    _validate_input_hash(input_hash)
    if decision.decision == "allow" and decision.require_review_artifact:
        if required_review_artifact_id is None:
            raise ValueError("required_review_artifact_id is required for auto-allow.")

    metadata = _trace_metadata(decision)
    policy_payload: dict[str, Any] = {
        "run_id": run_id,
        "approval_request_id": approval_request_id,
        "actor_id": actor_id,
        "action_class": decision.action_class,
        "decision": decision.decision,
        "policy_profile": decision.policy_profile,
        "profile_resolved_effect": decision.profile_resolved_effect,
        "required_review_artifact_id": required_review_artifact_id,
        "reason_code": decision.reason_code,
        "policy_version": policy_version,
        "input_hash": input_hash,
        "metadata_": metadata,
    }
    event_summary = _event_summary(
        decision=decision,
        actor_id=actor_id,
        run_id=run_id,
        policy_version=policy_version,
        input_hash=input_hash,
        required_review_artifact_id=required_review_artifact_id,
        policy_decision_id=policy_decision_id,
    )
    audit_payload = {
        "redacted": True,
        "policy_decision": event_summary,
    }
    agent_event_payload = {
        "redacted": True,
        "policy_decision": event_summary,
    }

    for path, payload in (
        ("$policy_decision_payload", policy_payload),
        ("$audit_payload", audit_payload),
        ("$agent_event_payload", agent_event_payload),
    ):
        assert_no_raw_secret(_json_safe_for_scan(payload), path=path)

    return AutonomyPolicyTracePayloads(
        policy_decision_payload=policy_payload,
        audit_event_type=AUTONOMY_POLICY_AUDIT_EVENT_TYPE,
        audit_payload=audit_payload,
        agent_event_type=AUTONOMY_POLICY_AGENT_EVENT_TYPE,
        agent_event_payload=agent_event_payload,
    )


def _trace_metadata(decision: AutonomyPolicyEngineDecision) -> dict[str, Any]:
    return {
        "rls_ready": True,
        "trace_kind": "autonomy_policy_decision",
        "applied_level": decision.autonomy_level,
        "effective_action_class": decision.action_class,
        "auto_allow_reason": (
            decision.reason_code if decision.decision == "allow" else None
        ),
        "policy_engine_reason_code": decision.reason_code,
        "profile_reason_code": decision.profile_reason_code,
        "low_risk_failed_axes": list(decision.low_risk_failed_axes),
        "override_source": decision.override_source,
        "required_review_artifact": decision.require_review_artifact,
    }


def _event_summary(
    *,
    decision: AutonomyPolicyEngineDecision,
    actor_id: UUID,
    run_id: UUID,
    policy_version: str,
    input_hash: str,
    required_review_artifact_id: UUID | None,
    policy_decision_id: UUID | None,
) -> dict[str, Any]:
    return {
        "policy_decision_id": _uuid_or_none(policy_decision_id),
        "run_id": str(run_id),
        "actor_id": str(actor_id),
        "decision": decision.decision,
        "policy_profile": decision.policy_profile,
        "profile_resolved_effect": decision.profile_resolved_effect,
        "policy_version": policy_version,
        "input_hash": input_hash,
        "applied_level": decision.autonomy_level,
        "effective_action_class": decision.action_class,
        "auto_allow_reason": (
            decision.reason_code if decision.decision == "allow" else None
        ),
        "policy_engine_reason_code": decision.reason_code,
        "profile_reason_code": decision.profile_reason_code,
        "low_risk_failed_axes": list(decision.low_risk_failed_axes),
        "override_source": decision.override_source,
        "required_review_artifact": decision.require_review_artifact,
        "required_review_artifact_id": _uuid_or_none(required_review_artifact_id),
    }


def _validate_policy_version(policy_version: str) -> None:
    if not policy_version.strip():
        raise ValueError("policy_version must be non-empty.")


def _validate_input_hash(input_hash: str) -> None:
    if not _SHA256_HEX_RE.fullmatch(input_hash):
        raise ValueError("input_hash must be a lowercase SHA-256 hex digest.")


def _uuid_or_none(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def _json_safe_for_scan(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe_for_scan(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe_for_scan(item) for item in value]
    return value


__all__ = [
    "AUTONOMY_POLICY_AGENT_EVENT_TYPE",
    "AUTONOMY_POLICY_AUDIT_EVENT_TYPE",
    "AutonomyPolicyTracePayloads",
    "AutonomyPolicyTraceRecord",
    "append_autonomy_policy_trace",
    "build_autonomy_policy_trace_payloads",
]
