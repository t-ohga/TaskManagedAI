from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.policy.autonomy_policy_engine import AutonomyPolicyEngineDecision
from backend.app.services.policy.autonomy_trace import (
    AUTONOMY_POLICY_AGENT_EVENT_TYPE,
    AUTONOMY_POLICY_AUDIT_EVENT_TYPE,
    append_autonomy_policy_trace,
    build_autonomy_policy_trace_payloads,
)

ACTOR_ID = UUID("00000000-0000-4000-8000-0000000000a1")
RUN_ID = UUID("00000000-0000-4000-8000-0000000000b1")
POLICY_DECISION_ID = UUID("00000000-0000-4000-8000-0000000000c1")
REVIEW_ARTIFACT_ID = UUID("00000000-0000-4000-8000-0000000000d1")
INPUT_HASH = "a" * 64


def _decision(
    *,
    decision: str = "allow",
    reason_code: str = "autonomy_matrix_auto_allow_applied",
    require_review_artifact: bool = True,
) -> AutonomyPolicyEngineDecision:
    return AutonomyPolicyEngineDecision(
        autonomy_level="L3",
        policy_profile="default",
        action_class="repo_write",
        decision=decision,  # type: ignore[arg-type]
        profile_resolved_effect="require_approval",
        require_review_artifact=require_review_artifact,
        reason_code=reason_code,  # type: ignore[arg-type]
        profile_reason_code="policy_profile_action_effect_resolved",
        low_risk_failed_axes=(),
        override_source=None,
    )


def test_trace_payloads_record_auto_allow_without_raw_payload_surfaces() -> None:
    payloads = build_autonomy_policy_trace_payloads(
        decision=_decision(),
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        policy_version="2026-05-24-autonomy",
        input_hash=INPUT_HASH,
        required_review_artifact_id=REVIEW_ARTIFACT_ID,
        policy_decision_id=POLICY_DECISION_ID,
    )

    assert payloads.audit_event_type == AUTONOMY_POLICY_AUDIT_EVENT_TYPE
    assert payloads.agent_event_type == AUTONOMY_POLICY_AGENT_EVENT_TYPE
    assert payloads.policy_decision_payload["decision"] == "allow"
    assert payloads.policy_decision_payload["policy_profile"] == "default"
    assert payloads.policy_decision_payload["profile_resolved_effect"] == "require_approval"
    assert payloads.policy_decision_payload["input_hash"] == INPUT_HASH
    assert payloads.policy_decision_payload["metadata_"] == {
        "rls_ready": True,
        "trace_kind": "autonomy_policy_decision",
        "applied_level": "L3",
        "effective_action_class": "repo_write",
        "auto_allow_reason": "autonomy_matrix_auto_allow_applied",
        "policy_engine_reason_code": "autonomy_matrix_auto_allow_applied",
        "profile_reason_code": "policy_profile_action_effect_resolved",
        "low_risk_failed_axes": [],
        "override_source": None,
        "required_review_artifact": True,
    }
    assert payloads.audit_payload["redacted"] is True
    assert payloads.agent_event_payload["redacted"] is True
    assert payloads.audit_payload["policy_decision"]["policy_decision_id"] == str(
        POLICY_DECISION_ID
    )

    assert_no_raw_secret(payloads.policy_decision_payload["metadata_"])
    assert_no_raw_secret(payloads.audit_payload)
    assert_no_raw_secret(payloads.agent_event_payload)


def test_trace_payloads_reject_auto_allow_without_required_review_artifact() -> None:
    with pytest.raises(ValueError, match="required_review_artifact_id"):
        build_autonomy_policy_trace_payloads(
            decision=_decision(),
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            policy_version="2026-05-24-autonomy",
            input_hash=INPUT_HASH,
        )


@pytest.mark.parametrize(
    "input_hash",
    [
        "",
        "A" * 64,
        "raw prompt text",
        "sk-" + ("x" * 40),
    ],
)
def test_trace_payloads_accept_only_lowercase_sha256_input_hash(input_hash: str) -> None:
    with pytest.raises(ValueError, match="input_hash"):
        build_autonomy_policy_trace_payloads(
            decision=_decision(decision="require_approval", require_review_artifact=False),
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            policy_version="2026-05-24-autonomy",
            input_hash=input_hash,
        )


def test_trace_signature_has_no_raw_payload_inputs() -> None:
    parameters = inspect.signature(append_autonomy_policy_trace).parameters

    forbidden = {
        "raw_prompt",
        "prompt",
        "provider_payload",
        "raw_provider_payload",
        "capability_token",
        "secret_capability_token",
        "raw_secret",
    }
    assert forbidden.isdisjoint(parameters)


@pytest.mark.asyncio
async def test_append_trace_calls_three_append_only_ledgers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakePolicyDecisionRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def append(self, tenant_id: int, **payload: object) -> SimpleNamespace:
            calls.append(("policy_decision", {"tenant_id": tenant_id, "payload": payload}))
            return SimpleNamespace(id=POLICY_DECISION_ID)

    class FakeAuditEventRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def append(self, **payload: object) -> SimpleNamespace:
            calls.append(("audit_event", payload))
            return SimpleNamespace(id=UUID("00000000-0000-4000-8000-0000000000e1"))

    class FakeAgentRunEventRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def append_event(self, **payload: object) -> SimpleNamespace:
            calls.append(("agent_event", payload))
            return SimpleNamespace(id=UUID("00000000-0000-4000-8000-0000000000f1"))

    monkeypatch.setattr(
        "backend.app.services.policy.autonomy_trace.PolicyDecisionRepository",
        FakePolicyDecisionRepository,
    )
    monkeypatch.setattr(
        "backend.app.services.policy.autonomy_trace.AuditEventRepository",
        FakeAuditEventRepository,
    )
    monkeypatch.setattr(
        "backend.app.services.policy.autonomy_trace.AgentRunEventRepository",
        FakeAgentRunEventRepository,
    )

    await append_autonomy_policy_trace(
        object(),  # type: ignore[arg-type]
        tenant_id=1,
        decision=_decision(),
        actor_id=ACTOR_ID,
        run_id=RUN_ID,
        policy_version="2026-05-24-autonomy",
        input_hash=INPUT_HASH,
        required_review_artifact_id=REVIEW_ARTIFACT_ID,
    )

    assert [name for name, _payload in calls] == [
        "policy_decision",
        "audit_event",
        "agent_event",
    ]
    audit_payload = calls[1][1]["payload"]
    agent_payload = calls[2][1]["event_payload"]
    assert audit_payload["policy_decision"]["policy_decision_id"] == str(
        POLICY_DECISION_ID
    )
    assert agent_payload["policy_decision"]["policy_decision_id"] == str(
        POLICY_DECISION_ID
    )
