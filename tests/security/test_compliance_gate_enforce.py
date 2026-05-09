from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest

import backend.app.services.providers.compliance_gate as compliance_gate_module
from backend.app.domain.provider.compliance import ComplianceMatrixEntry
from backend.app.domain.provider.request import ProviderMessage, ProviderRequest
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.providers.compliance_gate import ComplianceGate
from backend.app.services.providers.matrix_loader import (
    ComplianceMatrix as LoadedComplianceMatrix,
)

RUN_ID = UUID("00000000-0000-4000-8000-000000005711")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000005712")


@dataclass
class _Run:
    tenant_id: int = 1
    id: UUID = RUN_ID
    status: str = "running"
    blocked_reason: str | None = None
    policy_version: str = "policy-test-v1"
    trace_id: str = "trace-test"
    correlation_id: str = "correlation-test"


class _AuditEmitter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def append(
        self,
        *,
        tenant_id: int,
        event_type: str,
        payload: dict[str, Any],
        actor_id: UUID | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.events.append(
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "payload": payload,
                "actor_id": actor_id,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            }
        )


def _entry(**overrides: Any) -> ComplianceMatrixEntry:
    payload: dict[str, Any] = {
        "provider": "mock",
        "api_or_feature": "mock",
        "zdr_eligible": "yes",
        "retention": "0d",
        "training_use": "no",
        "region_or_data_transfer": "verified",
        "subprocessor_or_doc_url": "repository-docs",
        "plan_required": "enterprise",
        "allowed_data_class": "internal",
        "condition_status": "not_applicable",
        "p0_policy_note": "test row",
        "last_verified_at": "2026-05-09",
    }
    payload.update(overrides)
    return ComplianceMatrixEntry.model_validate(payload)


def _matrix(entry: ComplianceMatrixEntry) -> LoadedComplianceMatrix:
    return LoadedComplianceMatrix(
        {(entry.provider, entry.api_or_feature): entry},
        matrix_version="pcm-v1",
    )


def _provider_request(*, payload_data_class: str = "internal") -> ProviderRequest:
    return ProviderRequest.model_validate(
        {
            "tenant_id": 1,
            "run_id": RUN_ID,
            "provider": "mock",
            "api_or_feature": "mock",
            "model_resolved": "mock-model",
            "messages": [{"role": "user", "content": "hello"}],
            "structured_output_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
            },
            "payload_data_class": payload_data_class,
            "provider_compliance_matrix_version": "pcm-v1",
            "max_tokens": 256,
            "temperature": 0,
            "safety_settings": {"mode": "test"},
            "secret_capability_token": "opaque-broker-token-for-test",
        }
    )


@pytest.fixture
def transition_spy(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_transition(session: Any, **kwargs: Any) -> object:
        calls.append(kwargs)
        run = kwargs["run"]
        run.status = kwargs["to_state"]
        run.blocked_reason = kwargs["blocked_reason"]
        return object()

    monkeypatch.setattr(compliance_gate_module, "transition_with_event", fake_transition)
    return calls


@pytest.mark.asyncio
async def test_enforce_deny_emits_policy_decision_and_blocks_transition(
    transition_spy: list[dict[str, Any]],
) -> None:
    audit = _AuditEmitter()
    gate = ComplianceGate(
        matrix_loader=_matrix(_entry(allowed_data_class="internal")),
        audit_emitter=audit,
    )

    decision, result = await gate.enforce(
        object(),
        run=_Run(),
        request=_provider_request(payload_data_class="confidential"),
        actor_id=ACTOR_ID,
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "payload_data_class_exceeds_allowed"
    assert result is not None
    assert result.status == "data_class_deny"

    assert [event["event_type"] for event in audit.events] == ["policy_decision_created"]
    assert audit.events[0]["actor_id"] == ACTOR_ID
    payload = audit.events[0]["payload"]
    assert payload["event_taxonomy"] == "audit_event"
    assert payload["decision"] == "deny"
    assert payload["reason_code"] == "payload_data_class_exceeds_allowed"
    assert payload["provider_compliance_matrix_version"] == "pcm-v1"
    assert payload["actor_id"] == str(ACTOR_ID)
    assert_no_raw_secret(payload, path="$test_audit_payload")

    serialized = json.dumps(payload, sort_keys=True)
    assert "opaque-broker-token-for-test" not in serialized
    assert transition_spy[0]["to_state"] == "blocked"
    assert transition_spy[0]["event_type"] == "policy_blocked"
    assert transition_spy[0]["blocked_reason"] == "policy_blocked"
    assert transition_spy[0]["actor_id"] == ACTOR_ID
    assert transition_spy[0]["payload"]["audit_event_type"] == "policy_decision_created"


@pytest.mark.asyncio
async def test_enforce_requires_actor_id_kw_only(
    transition_spy: list[dict[str, Any]],
) -> None:
    audit = _AuditEmitter()
    gate = ComplianceGate(
        matrix_loader=_matrix(_entry(allowed_data_class="internal")),
        audit_emitter=audit,
    )

    with pytest.raises(TypeError, match="actor_id"):
        await gate.enforce(object(), run=_Run(), request=_provider_request())

    assert audit.events == []
    assert transition_spy == []


@pytest.mark.asyncio
async def test_enforce_allow_returns_none_for_provider_result(
    transition_spy: list[dict[str, Any]],
) -> None:
    audit = _AuditEmitter()
    gate = ComplianceGate(
        matrix_loader=_matrix(_entry(allowed_data_class="internal")),
        audit_emitter=audit,
    )

    decision, result = await gate.enforce(
        object(),
        run=_Run(),
        request=_provider_request(),
        actor_id=ACTOR_ID,
    )

    assert decision.decision == "allow"
    assert decision.reason_code == "allow"
    assert result is None
    assert transition_spy == []
    assert [event["event_type"] for event in audit.events] == ["policy_decision_created"]
    assert audit.events[0]["actor_id"] == ACTOR_ID
    assert audit.events[0]["payload"]["decision"] == "allow"
    assert audit.events[0]["payload"]["actor_id"] == str(ACTOR_ID)


@pytest.mark.asyncio
async def test_enforce_rejects_cross_tenant_run_request_mismatch(
    transition_spy: list[dict[str, Any]],
) -> None:
    audit = _AuditEmitter()
    gate = ComplianceGate(
        matrix_loader=_matrix(_entry(allowed_data_class="internal")),
        audit_emitter=audit,
    )

    with pytest.raises(ValueError, match="tenant_id"):
        await gate.enforce(
            object(),
            run=_Run(tenant_id=2),
            request=_provider_request(),
            actor_id=ACTOR_ID,
        )

    assert audit.events == []
    assert transition_spy == []


@pytest.mark.asyncio
async def test_preflight_deny_emits_audit_events_and_policy_blocked_transition(
    transition_spy: list[dict[str, Any]],
) -> None:
    audit = _AuditEmitter()
    gate = ComplianceGate(
        matrix_loader=_matrix(_entry(allowed_data_class="internal")),
        audit_emitter=audit,
    )
    provider_request = ProviderRequest.model_construct(
        tenant_id=1,
        run_id=RUN_ID,
        provider="mock",
        api_or_feature="mock",
        model_resolved="mock-model",
        messages=[
            ProviderMessage.model_construct(
                role="user",
                content={"api_key": "redacted"},
            )
        ],
        structured_output_schema={"type": "object"},
        payload_data_class="internal",
        provider_compliance_matrix_version="pcm-v1",
        max_tokens=256,
        temperature=0,
        safety_settings={"mode": "test"},
        secret_capability_token=None,
    )

    decision, result = await gate.enforce(
        object(),
        run=_Run(),
        request=provider_request,
        actor_id=ACTOR_ID,
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "provider_request_preflight_violation"
    assert result is not None
    assert result.status == "preflight_deny"
    assert [event["event_type"] for event in audit.events] == [
        "policy_decision_created",
        "provider_blocked",
    ]
    assert {event["payload"]["event_taxonomy"] for event in audit.events} == {"audit_event"}
    assert audit.events[1]["payload"]["pattern_hit_kind"] == "prohibited_key:api_key"
    assert audit.events[1]["payload"]["actor_id"] == str(ACTOR_ID)
    assert transition_spy[0]["event_type"] == "policy_blocked"
    assert transition_spy[0]["payload"]["audit_event_type"] == "provider_blocked"
    assert "provider_blocked" not in {call["event_type"] for call in transition_spy}

