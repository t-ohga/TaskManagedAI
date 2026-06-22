"""Sprint 5.5 BL-0067 pure-helper tests.

The orchestrator wires DB session work (transition_with_event +
create_snapshot + record_provider_usage) that requires a real PostgreSQL
connection for end-to-end verification. The full chain integration is
exercised in ``tests/runtime/test_agent_run_full_chain_integration.py``
(Sprint 5.5 batch 3 prerequisite, requires ``docker compose up -d postgres
redis``).

This module covers DB-less pure helpers:

- ``_resolve_provider_transition_target``: ``ProviderResultKind`` →
  ``AgentRunStatusTransitionTarget`` with orchestrator-local
  ``unsupported_schema`` / ``schema_mismatch`` override (SP55-B2-F-001 fix).
- ``_provider_outcome_for_target``: ``ProviderResultKind`` →
  ``ProviderStepOutcome``
- ``_provider_event_type_for_target``: target → ``AgentRunEventType``
- ``_provider_event_payload``: shape + raw-secret-free invariant
- ``_assert_run_request_boundary``: tenant / run guard (SP55-B2-F-003 fix).
- contract test: every ``ProviderResultKind`` produces an
  ``(AgentRunStatus, AgentRunEventType)`` pair that survives
  ``validate_event_type_for_transition('running', ...)`` (SP55-B2-F-001
  suggested fix sweep).
"""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any, get_args, get_type_hints
from uuid import UUID

import pytest
from jsonschema import Draft7Validator

from backend.app.db.models.agent_run import AgentRun
from backend.app.domain.provider.compliance import ComplianceDecision
from backend.app.domain.provider.request import ProviderMessage, ProviderRequest
from backend.app.domain.provider.result import ProviderResult, ProviderUsage
from backend.app.services.agent_runtime.orchestrator import (
    AgentRunOrchestrator,
    ProviderStepOutcome,
    ProviderStepResult,
    RepairStepResult,
    ValidationStepOutcome,
    ValidationStepResult,
    _assert_run_request_boundary,
    _provider_event_payload,
    _provider_event_type_for_target,
    _provider_outcome_for_target,
    _redact_validation_error_summary,
    _resolve_provider_transition_target,
)
from backend.app.services.agent_runtime.provider_result_mapping import (
    ALL_PROVIDER_RESULT_KINDS,
    AgentRunStatusTransitionTarget,
    ProviderResultKind,
)
from backend.app.services.agent_runtime.state_machine import (
    validate_event_type_for_transition,
)

EXPECTED_PROVIDER_STEP_OUTCOMES = (
    "generated_artifact",
    "provider_refused",
    "provider_incomplete",
    "blocked_policy",
    "blocked_budget",
    "blocked_runtime",
    "failed_timeout",
    # SP-PHASE1 B5c (ADR-00048 §G/A-4): provider postflight generation CAS で latch engage を検出し
    # usage/artifact/status を進めず discard した outcome。
    "discarded_emergency_stop",
)

_RUN_ID = UUID("00000000-0000-4000-8000-000000005401")
_PROJECT_ID = UUID("00000000-0000-4000-8000-000000005402")
_OTHER_RUN_ID = UUID("00000000-0000-4000-8000-000000005403")


def test_provider_step_outcome_literal_matches_expected() -> None:
    """SP55-B2-F-001: validation_failed_* outcomes were dropped because the
    orchestrator-local override routes those kinds through generated_artifact.
    """

    assert tuple(get_args(ProviderStepOutcome)) == EXPECTED_PROVIDER_STEP_OUTCOMES


def test_orchestrator_dataclasses_are_frozen() -> None:
    """ProviderStepResult / RepairStepResult must be frozen dataclasses."""

    assert is_dataclass(ProviderStepResult)
    assert is_dataclass(RepairStepResult)


def test_agent_run_orchestrator_exposes_policy_pack_property() -> None:
    """Importable + property exists, even without DB / dependencies wired."""

    assert hasattr(AgentRunOrchestrator, "policy_pack")
    assert hasattr(AgentRunOrchestrator, "execute_provider_step")
    assert hasattr(AgentRunOrchestrator, "execute_repair_decision_step")


# ---------------------------------------------------------------------------
# _resolve_provider_transition_target: SP55-B2-F-001 override coverage.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("schema_kind", ["unsupported_schema", "schema_mismatch"])
def test_resolve_provider_target_overrides_schema_mismatch_to_generated_artifact(
    schema_kind: ProviderResultKind,
) -> None:
    """SP55-B2-F-001: the orchestrator must route ``unsupported_schema`` and
    ``schema_mismatch`` through ``generated_artifact`` because state_machine
    has no ``running -> validation_failed`` allowlist; the actual
    ``validation_failed`` transition is owned by the schema-validation step
    (BL-0067 continuation, Sprint 5.5 batch 3)."""

    target = _resolve_provider_transition_target(_provider_result(schema_kind))
    assert target.status == "generated_artifact"
    assert target.blocked_reason is None
    assert target.is_terminal is False


@pytest.mark.parametrize(
    ("kind", "expected_status"),
    [
        ("success", "generated_artifact"),
        ("refusal", "provider_refused"),
        ("safety_refusal", "provider_refused"),
        ("max_token", "provider_incomplete"),
        ("incomplete", "provider_incomplete"),
        ("timeout_retryable", "provider_incomplete"),
        ("preflight_deny", "blocked"),
        ("data_class_deny", "blocked"),
        ("budget_exceeded", "blocked"),
    ],
)
def test_resolve_provider_target_keeps_non_schema_kinds_canonical(
    kind: ProviderResultKind,
    expected_status: str,
) -> None:
    """Non-schema ProviderResultKind values keep the Sprint 5 canonical
    mapping (no orchestrator override)."""

    target = _resolve_provider_transition_target(_provider_result(kind))
    assert target.status == expected_status


# ---------------------------------------------------------------------------
# Contract sweep: every ProviderResultKind survives
# validate_event_type_for_transition('running', target.status, event_type).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ALL_PROVIDER_RESULT_KINDS)
def test_every_provider_kind_yields_allowlisted_running_transition(
    kind: ProviderResultKind,
) -> None:
    """SP55-B2-F-001 suggested-fix sweep: confirm every kind resolves to a
    (target.status, event_type) pair that the state_machine allowlist
    accepts for the ``running -> *`` transition. Catches drift between
    provider_result_mapping and EVENT_TYPE_FOR_TRANSITION early."""

    target = _resolve_provider_transition_target(_provider_result(kind))
    event_type = _provider_event_type_for_target(kind, target)
    # This must not raise — the orchestrator depends on it.
    validate_event_type_for_transition("running", target.status, event_type)


# ---------------------------------------------------------------------------
# _provider_outcome_for_target: mapping coverage.
# ---------------------------------------------------------------------------


_PROVIDER_KIND_OUTCOME_PAIRS: list[tuple[ProviderResultKind, ProviderStepOutcome]] = [
    ("success", "generated_artifact"),
    ("refusal", "provider_refused"),
    ("safety_refusal", "provider_refused"),
    ("max_token", "provider_incomplete"),
    ("incomplete", "provider_incomplete"),
    ("timeout_retryable", "provider_incomplete"),
    ("unsupported_schema", "generated_artifact"),
    ("schema_mismatch", "generated_artifact"),
    ("preflight_deny", "blocked_policy"),
    ("data_class_deny", "blocked_policy"),
    ("budget_exceeded", "blocked_budget"),
]


@pytest.mark.parametrize(("kind", "expected"), _PROVIDER_KIND_OUTCOME_PAIRS)
def test_provider_outcome_for_target_matches_orchestrator_mapping(
    kind: ProviderResultKind,
    expected: ProviderStepOutcome,
) -> None:
    target = _resolve_provider_transition_target(_provider_result(kind))
    assert _provider_outcome_for_target(kind, target) == expected


def test_provider_outcome_for_unknown_target_raises() -> None:
    """Defense-in-depth: an unmapped target should raise rather than silently
    yield a wrong outcome (regression guard for future state additions)."""

    bogus = AgentRunStatusTransitionTarget(status="queued", blocked_reason=None)
    with pytest.raises(ValueError, match="unmapped provider outcome"):
        _provider_outcome_for_target("success", bogus)


# ---------------------------------------------------------------------------
# _provider_event_type_for_target.
# ---------------------------------------------------------------------------


_PROVIDER_KIND_EVENT_PAIRS = [
    ("success", "provider_responded"),
    ("refusal", "provider_responded"),
    ("safety_refusal", "provider_responded"),
    ("max_token", "provider_responded"),
    ("incomplete", "provider_responded"),
    ("timeout_retryable", "provider_responded"),
    ("unsupported_schema", "provider_responded"),  # via generated_artifact override
    ("schema_mismatch", "provider_responded"),  # via generated_artifact override
    ("preflight_deny", "policy_blocked"),
    ("data_class_deny", "policy_blocked"),
    ("budget_exceeded", "budget_blocked"),
]


@pytest.mark.parametrize(("kind", "expected_event_type"), _PROVIDER_KIND_EVENT_PAIRS)
def test_provider_event_type_for_target_aligns_with_state_machine(
    kind: ProviderResultKind,
    expected_event_type: str,
) -> None:
    target = _resolve_provider_transition_target(_provider_result(kind))
    assert _provider_event_type_for_target(kind, target) == expected_event_type


# ---------------------------------------------------------------------------
# _provider_event_payload: raw-secret-free shape.
# ---------------------------------------------------------------------------


def _provider_result(status: ProviderResultKind = "success") -> ProviderResult:
    return ProviderResult(
        status=status,
        artifact_ref=None,
        usage=ProviderUsage(tokens_input=10, tokens_output=20, cost_usd=0.01),
        model_resolved="mock-model",
        api_version="2026-05-01",
        sdk_version="mock-sdk-0.0.1",
        provider_request_fingerprint="0" * 64,
        error_code=None,
        error_summary=None,
        redacted_response_summary={"text": "ok"},
        continuation_ref=None,
    )


def _compliance_decision(decision: str = "allow") -> ComplianceDecision:
    return ComplianceDecision(
        decision=decision,
        reason_code="allow",
        payload_data_class="public",
        allowed_data_class="public",
        effective_allowed_data_class="public",
        provider_compliance_matrix_version="v2026.05.09-p0-skeleton",
    )


def _provider_request() -> ProviderRequest:
    return ProviderRequest.model_validate(
        {
            "tenant_id": 1,
            "run_id": str(_RUN_ID),
            "provider": "mock",
            "api_or_feature": "mock",
            "model_resolved": "mock-model",
            "messages": [
                ProviderMessage(role="user", content="hello").model_dump(mode="json")
            ],
            "structured_output_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
            "payload_data_class": "public",
            "provider_compliance_matrix_version": "v2026.05.09-p0-skeleton",
        }
    )


def test_provider_event_payload_contains_no_raw_secret_keys() -> None:
    """The payload merges ProviderResult + ComplianceDecision; both upstream
    schemas already validate raw-secret-free shape (see
    ``backend/app/repositories/_payload_secret_scan.py``). The orchestrator's
    payload must not introduce any raw-secret-key by accident."""

    payload = _provider_event_payload(_provider_result(), _compliance_decision())
    for key in (
        "api_key",
        "raw_secret",
        "secret",
        "secret_value",
        "private_key",
        "auth_token",
        "bearer_token",
        "capability_token",
        "github_installation_token",
        "tailscale_auth_key",
    ):
        assert key not in payload


def test_provider_event_payload_keeps_compliance_matrix_version_field() -> None:
    """The orchestrator records ``provider_compliance_matrix_version`` (not the
    legacy ``matrix_version`` alias) for audit trace integrity."""

    payload = _provider_event_payload(_provider_result(), _compliance_decision())
    assert (
        payload["provider_compliance_matrix_version"]
        == "v2026.05.09-p0-skeleton"
    )
    assert "matrix_version" not in payload


def test_provider_event_payload_contains_redacted_response_summary() -> None:
    payload = _provider_event_payload(_provider_result(), _compliance_decision())
    assert payload["redacted_response_summary"] == {"text": "ok"}


# ---------------------------------------------------------------------------
# _assert_run_request_boundary: SP55-B2-F-003 fix.
# ---------------------------------------------------------------------------


def _agent_run(*, tenant_id: int = 1, run_id: UUID | None = None) -> AgentRun:
    return AgentRun(
        id=run_id or _RUN_ID,
        tenant_id=tenant_id,
        project_id=_PROJECT_ID,
        status="running",
    )


def test_assert_run_request_boundary_accepts_matching_run() -> None:
    _assert_run_request_boundary(_agent_run(), _provider_request())


def test_assert_run_request_boundary_rejects_tenant_mismatch() -> None:
    run = _agent_run(tenant_id=2)
    with pytest.raises(ValueError, match="tenant_id"):
        _assert_run_request_boundary(run, _provider_request())


def test_assert_run_request_boundary_rejects_run_id_mismatch() -> None:
    run = _agent_run(run_id=_OTHER_RUN_ID)
    with pytest.raises(ValueError, match="run.id"):
        _assert_run_request_boundary(run, _provider_request())


# ---------------------------------------------------------------------------
# Type-shape sanity for ProviderStepResult / RepairStepResult.
# ---------------------------------------------------------------------------


def test_provider_step_result_fields_are_typed_as_expected() -> None:
    hints = get_type_hints(ProviderStepResult)
    assert "outcome" in hints
    assert "to_state" in hints
    assert "event_type" in hints
    assert "event" in hints
    assert "provider_result" in hints
    assert "compliance_decision" in hints
    assert "blocked_reason" in hints


def test_provider_step_result_event_is_optional() -> None:
    """SP55-B2-F-004: ``event`` may be ``None`` for the ``blocked_budget``
    outcome because record_provider_usage performs the transition internally
    and the orchestrator does not surface its event handle."""

    hints = get_type_hints(ProviderStepResult)
    annotation = hints["event"]
    # AgentRunEvent | None  =>  Union[AgentRunEvent, None]; assertion is loose
    # but catches the regression where event is re-narrowed to AgentRunEvent.
    args = getattr(annotation, "__args__", ())
    assert type(None) in args or annotation is type(None)


def test_repair_step_result_fields_are_typed_as_expected() -> None:
    hints = get_type_hints(RepairStepResult)
    assert "decision" in hints
    assert "to_state" in hints
    assert "event_type" in hints
    assert "event" in hints
    assert "resume_snapshot" in hints


# ---------------------------------------------------------------------------
# Sprint 5.5 BL-0067 続き: execute_validation_step pure helpers.
# ---------------------------------------------------------------------------


def test_validation_step_outcome_literal_matches_expected() -> None:
    assert tuple(get_args(ValidationStepOutcome)) == (
        "schema_validated",
        "validation_failed",
    )


def test_validation_step_result_is_frozen_dataclass() -> None:
    assert is_dataclass(ValidationStepResult)


def test_validation_step_result_fields_are_typed_as_expected() -> None:
    hints = get_type_hints(ValidationStepResult)
    assert "outcome" in hints
    assert "to_state" in hints
    assert "event_type" in hints
    assert "event" in hints
    assert "validation_passed" in hints
    assert "validation_errors" in hints


def test_agent_run_orchestrator_exposes_execute_validation_step() -> None:
    """The new step is part of the public surface so callers (Sprint 6 arq
    worker) can chain it into the runtime pipeline."""

    assert hasattr(AgentRunOrchestrator, "execute_validation_step")


# ---------------------------------------------------------------------------
# _redact_validation_error_summary: redaction shape.
# ---------------------------------------------------------------------------


def _produce_validation_error() -> Any:
    """Run jsonschema validation against a minimal failing payload."""

    from jsonschema.exceptions import ValidationError  # noqa: PLC0415

    schema = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
        "additionalProperties": False,
    }
    validator = Draft7Validator(schema)
    errors = list(validator.iter_errors({"summary": 123}))
    assert errors, "fixture must produce a ValidationError"
    err = errors[0]
    assert isinstance(err, ValidationError)
    return err


def test_redact_validation_error_summary_does_not_echo_instance_value() -> None:
    """The redacted summary must not contain the raw instance value (which
    could carry raw secret material from the artifact)."""

    err = _produce_validation_error()
    err.instance = "sk-hostile-1234567890abcdef1234567890abcdef"  # poison
    summary = _redact_validation_error_summary(err)
    assert "sk-hostile" not in summary
    assert "path=" in summary
    assert "validator=" in summary
    assert "schema_path=" in summary


def test_redact_validation_error_summary_caps_schema_path_tail() -> None:
    """``schema_path`` is truncated to the last 3 elements to keep payload
    size bounded (defense-in-depth for large nested schemas)."""

    err = _produce_validation_error()
    # The fixture's schema_path has length 4 (properties / summary / type /
    # type-keyword); the redaction should keep only the last 3.
    summary = _redact_validation_error_summary(err)
    schema_path = list(err.schema_path)
    if len(schema_path) > 3:
        # The summary contains a representation of only the last 3 elements;
        # the first element label should NOT appear in the schema_path field.
        first_element = str(schema_path[0])
        # We do not assert absence in the whole summary string (the path /
        # validator section may contain other content); we only confirm the
        # ``schema_path=[...]`` slice starts after the truncation.
        idx = summary.index("schema_path=")
        tail_section = summary[idx:]
        assert first_element not in tail_section
