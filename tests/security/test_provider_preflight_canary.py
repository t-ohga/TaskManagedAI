from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

import backend.app.services.providers.compliance_gate as compliance_gate_module
from backend.app.domain.provider.compliance import ComplianceMatrixEntry
from backend.app.domain.provider.fingerprint import compute_provider_request_fingerprint
from backend.app.domain.provider.request import ProviderMessage, ProviderRequest
from backend.app.domain.provider.result import ProviderResult
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.providers.compliance_gate import ComplianceGate
from backend.app.services.providers.matrix_loader import (
    ComplianceMatrix as LoadedComplianceMatrix,
)
from eval.security.secret_canary.loader import PublicFixture, load_public_regression_fixtures

RUN_ID = UUID("00000000-0000-4000-8000-000000006301")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000006302")
BASE_PATH = Path("eval/security/secret_canary")


@dataclass
class _Run:
    tenant_id: int = 1
    id: UUID = RUN_ID
    status: str = "running"
    blocked_reason: str | None = None
    policy_version: str = "policy-fixture-v0"
    trace_id: str = "trace-fixture"
    correlation_id: str = "correlation-fixture"


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


class _CountingProviderAdapter:
    def __init__(self) -> None:
        self.execute_count = 0

    def execute(self, request: ProviderRequest) -> ProviderResult:
        self.execute_count += 1
        return ProviderResult(
            status="success",
            artifact_ref="fixture-artifact",
            usage=None,
            model_resolved=request.model_resolved,
            api_version="fixture-v1",
            sdk_version="fixture-sdk-v1",
            provider_request_fingerprint=compute_provider_request_fingerprint(
                request,
                matrix_version=request.provider_compliance_matrix_version,
                api_version="fixture-v1",
                sdk_version="fixture-sdk-v1",
            ),
            error_code=None,
            error_summary=None,
            redacted_response_summary={"ok": True},
            continuation_ref=None,
        )


def _entry(matrix_version: str) -> ComplianceMatrixEntry:
    return ComplianceMatrixEntry.model_validate(
        {
            "provider": "fixture-provider",
            "api_or_feature": "provider_request_preflight",
            "zdr_eligible": "yes",
            "retention": "0d",
            "training_use": "no",
            "region_or_data_transfer": "verified",
            "subprocessor_or_doc_url": "fixture",
            "plan_required": "enterprise",
            "allowed_data_class": "confidential",
            "condition_status": "not_applicable",
            "p0_policy_note": f"fixture-only provider row for {matrix_version}",
            "last_verified_at": "2026-05-09",
        }
    )


def _matrix(matrix_version: str) -> LoadedComplianceMatrix:
    entry = _entry(matrix_version)
    return LoadedComplianceMatrix(
        {(entry.provider, entry.api_or_feature): entry},
        matrix_version=matrix_version,
    )


def _request_from_fixture(fixture: PublicFixture) -> ProviderRequest:
    return ProviderRequest.model_construct(
        tenant_id=1,
        run_id=RUN_ID,
        provider="fixture-provider",
        api_or_feature="provider_request_preflight",
        model_resolved="fixture-model",
        messages=[
            ProviderMessage.model_construct(
                role="user",
                content="redacted AC-HARD-02 provider preflight fixture",
            )
        ],
        structured_output_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
        },
        payload_data_class=fixture.metadata["payload_data_class"],
        provider_compliance_matrix_version=fixture.metadata[
            "provider_compliance_matrix_version"
        ],
        max_tokens=256,
        temperature=0,
        safety_settings={"fixture_input": fixture.input},
        secret_capability_token=None,
    )


def _make_dummy_canary_marker() -> str:
    """Synthetic canary marker matching CANARY-FIXTURE-[A-Z0-9]{16,}."""

    return "CANARY-FIXTURE-" + "X" * 16


def _request_with_raw_canary_marker() -> ProviderRequest:
    return ProviderRequest.model_construct(
        tenant_id=1,
        run_id=RUN_ID,
        provider="fixture-provider",
        api_or_feature="provider_request_preflight",
        model_resolved="fixture-model",
        messages=[
            ProviderMessage.model_construct(
                role="user",
                content="redacted marker " + _make_dummy_canary_marker(),
            )
        ],
        structured_output_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
        },
        payload_data_class="confidential",
        provider_compliance_matrix_version="provider-matrix-fixture-v0",
        max_tokens=256,
        temperature=0,
        safety_settings={"mode": "test"},
        secret_capability_token=None,
    )


def _fixture(case_key: str) -> PublicFixture:
    fixtures = load_public_regression_fixtures(BASE_PATH)
    for fixture in fixtures:
        if fixture.case_key == case_key:
            return fixture
    raise AssertionError(f"fixture not found: {case_key}")


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
async def test_secret_canary_fixture_blocks_through_compliance_gate_preflight(
    transition_spy: list[dict[str, Any]],
) -> None:
    fixture = _fixture("canary_in_provider_request_preflight")
    provider_request = _request_from_fixture(fixture)
    audit = _AuditEmitter()
    gate = ComplianceGate(
        matrix_loader=_matrix(provider_request.provider_compliance_matrix_version),
        audit_emitter=audit,
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
    assert result.redacted_response_summary["pattern_hit_kind"] == "canary_pattern"

    assert [event["event_type"] for event in audit.events] == [
        "policy_decision_created",
        "provider_blocked",
    ]
    for event in audit.events:
        payload = event["payload"]
        assert event["actor_id"] == ACTOR_ID
        assert payload["event_taxonomy"] == "audit_event"
        assert payload["reason_code"] == "provider_request_preflight_violation"
        assert payload["pattern_hit_kind"] == "canary_pattern"
        assert payload["actor_id"] == str(ACTOR_ID)
        assert payload["redacted"] is True
        assert_no_raw_secret(payload, path="$canary_audit_payload")
        serialized = json.dumps(payload, sort_keys=True)
        assert fixture.input["task_summary"] not in serialized
        assert "scanner_pattern_ref" not in serialized

    assert transition_spy[0]["to_state"] == "blocked"
    assert transition_spy[0]["blocked_reason"] == "policy_blocked"
    assert transition_spy[0]["event_type"] == "policy_blocked"
    assert transition_spy[0]["actor_id"] == ACTOR_ID
    assert transition_spy[0]["payload"]["audit_event_type"] == "provider_blocked"

    for surface in ("provider_request_preflight", "artifact", "runner_stdout_stderr", "audit"):
        expected = fixture.expected_redaction[surface]
        assert expected["redacted"] is True
        assert expected["raw_value_present"] is False
        assert expected["pattern_hit_kind"] == "canary_pattern"


@pytest.mark.asyncio
async def test_raw_canary_marker_blocks_through_compliance_gate_preflight(
    transition_spy: list[dict[str, Any]],
) -> None:
    provider_request = _request_with_raw_canary_marker()
    marker = _make_dummy_canary_marker()
    audit = _AuditEmitter()
    gate = ComplianceGate(
        matrix_loader=_matrix(provider_request.provider_compliance_matrix_version),
        audit_emitter=audit,
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
    assert result.redacted_response_summary["pattern_hit_kind"] == "canary_pattern"
    assert [event["event_type"] for event in audit.events] == [
        "policy_decision_created",
        "provider_blocked",
    ]

    for event in audit.events:
        serialized = json.dumps(event["payload"], sort_keys=True)
        assert marker not in serialized
        assert event["payload"]["pattern_hit_kind"] == "canary_pattern"
        assert_no_raw_secret(event["payload"], path="$raw_canary_audit_payload")

    transition_payload = transition_spy[0]["payload"]
    assert transition_spy[0]["event_type"] == "policy_blocked"
    assert transition_payload["pattern_hit_kind"] == "canary_pattern"
    assert marker not in json.dumps(transition_payload, sort_keys=True)


@pytest.mark.asyncio
async def test_control_no_canary_allows_provider_adapter_execute(
    transition_spy: list[dict[str, Any]],
) -> None:
    fixture = _fixture("control_no_canary_allows_provider_preflight")
    provider_request = _request_from_fixture(fixture)
    audit = _AuditEmitter()
    gate = ComplianceGate(
        matrix_loader=_matrix(provider_request.provider_compliance_matrix_version),
        audit_emitter=audit,
    )
    adapter = _CountingProviderAdapter()

    decision, result = await gate.enforce(
        object(),
        run=_Run(),
        request=provider_request,
        actor_id=ACTOR_ID,
    )

    assert decision.decision == "allow"
    assert decision.reason_code == "allow"
    assert result is None
    assert transition_spy == []
    assert [event["event_type"] for event in audit.events] == ["policy_decision_created"]
    assert audit.events[0]["actor_id"] == ACTOR_ID
    assert audit.events[0]["payload"]["decision"] == "allow"
    assert audit.events[0]["payload"]["reason_code"] == "allow"
    assert audit.events[0]["payload"]["pattern_hit_kind"] == "none"
    assert audit.events[0]["payload"]["actor_id"] == str(ACTOR_ID)

    provider_result = adapter.execute(provider_request)

    assert adapter.execute_count == 1
    assert provider_result.status == "success"
    assert {event["event_type"] for event in audit.events} == {"policy_decision_created"}

    for surface in ("provider_request_preflight", "artifact", "runner_stdout_stderr", "audit"):
        expected = fixture.expected_redaction[surface]
        assert expected["redacted"] is False
        assert expected["raw_value_present"] is False
        assert expected["pattern_hit_kind"] == "none"

