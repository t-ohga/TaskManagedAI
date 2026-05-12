"""Sprint 5.5 BL-0067 続き: ``execute_validation_step`` behavior tests.

SP55-B4-F-002 fix: covers the orchestrator method's core branching
(tenant/run boundary guard, pass → schema_validated, fail →
validation_failed, redacted error summaries, transition_with_event payload
shape) WITHOUT requiring a real PostgreSQL connection. The
``transition_with_event`` import is monkeypatched on the orchestrator
module so the step can be exercised end-to-end at the service-layer
contract level.

Full DB integration (``transition_with_event`` writing rows, ContextSnapshot
side-effects, AgentRunEvent append sequence) is exercised by
``tests/runtime/test_agent_run_full_chain_integration.py`` (deferred to the
next batch / Sprint with Docker postgres setup).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

import pytest

from backend.app.services.agent_runtime import orchestrator as orchestrator_module
from backend.app.services.agent_runtime.orchestrator import (
    AgentRunOrchestrator,
    ValidationStepResult,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.app.domain.provider.adapter import ProviderAdapter
    from backend.app.services.providers.compliance_gate import ComplianceGate


@pytest.fixture
def captured_transitions() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def patched_transition(
    monkeypatch: pytest.MonkeyPatch,
    captured_transitions: list[dict[str, Any]],
) -> None:
    """Replace ``transition_with_event`` import on the orchestrator module
    with a recorder coroutine so the step can run without a DB session."""

    async def _fake_transition_with_event(
        session: Any,
        *,
        run: Any,
        to_state: str,
        event_type: str,
        payload: dict[str, Any],
        actor_id: UUID,
        blocked_reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        captured_transitions.append(
            {
                "to_state": to_state,
                "event_type": event_type,
                "payload": payload,
                "actor_id": actor_id,
                "blocked_reason": blocked_reason,
                "idempotency_key": idempotency_key,
            }
        )
        # Mimic the return value of the real ``transition_with_event``: an
        # AgentRunEvent-shaped object. The pure-helper tests only check
        # ``ValidationStepResult.event``'s presence.
        return SimpleNamespace(
            id=uuid4(),
            event_type=event_type,
            payload=payload,
        )

    monkeypatch.setattr(
        orchestrator_module,
        "transition_with_event",
        _fake_transition_with_event,
    )


def _make_run(
    *,
    tenant_id: int = 1,
    run_id: UUID | None = None,
) -> Any:
    return SimpleNamespace(
        id=run_id or uuid4(),
        tenant_id=tenant_id,
        project_id=uuid4(),
        status="generated_artifact",
    )


def _make_artifact(
    *,
    run: Any,
    content_jsonb: dict[str, Any] | None = None,
    content_hash: str = "0" * 64,
    payload_data_class: str = "public",
) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=run.tenant_id,
        run_id=run.id,
        kind="plan",
        content_hash=content_hash,
        content_jsonb=content_jsonb or {"summary": "ok", "version": 1},
        payload_data_class=payload_data_class,
    )


def _schema_pass() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["summary"],
        "properties": {
            "summary": {"type": "string"},
            "version": {"type": "integer"},
        },
        "additionalProperties": False,
    }


def _schema_strict_summary() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string", "minLength": 5}},
        "additionalProperties": False,
    }


def _make_orchestrator() -> AgentRunOrchestrator:
    """Build an orchestrator with mock dependencies (DB-less unit test).

    SP55-B4-R4-F-001 fix: cast SimpleNamespace stand-ins to the typed
    dependency protocols so mypy stays clean without ``# type: ignore``.
    The methods exercised by execute_validation_step (transition_with_event
    via monkeypatch) do not actually invoke the session / compliance_gate /
    provider, so the casts are safe for this unit test surface.
    """

    return AgentRunOrchestrator(
        session=cast("AsyncSession", SimpleNamespace()),
        compliance_gate=cast("ComplianceGate", SimpleNamespace()),
        provider=cast("ProviderAdapter", SimpleNamespace()),
        policy_pack=None,
    )


# ---------------------------------------------------------------------------
# tenant / run boundary guard.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_validation_step_rejects_tenant_mismatch(
    patched_transition: None,
    captured_transitions: list[dict[str, Any]],
) -> None:
    run = _make_run(tenant_id=1)
    artifact = _make_artifact(run=run)
    artifact.tenant_id = 2  # hostile mismatch

    with pytest.raises(ValueError, match="artifact.tenant_id"):
        await _make_orchestrator().execute_validation_step(
            run=run,
            artifact=artifact,
            schema=_schema_pass(),
            actor_id=uuid4(),
        )
    assert captured_transitions == []  # transition not invoked


@pytest.mark.asyncio
async def test_execute_validation_step_rejects_run_id_mismatch(
    patched_transition: None,
    captured_transitions: list[dict[str, Any]],
) -> None:
    run = _make_run()
    artifact = _make_artifact(run=run)
    artifact.run_id = uuid4()  # hostile mismatch

    with pytest.raises(ValueError, match="artifact.run_id"):
        await _make_orchestrator().execute_validation_step(
            run=run,
            artifact=artifact,
            schema=_schema_pass(),
            actor_id=uuid4(),
        )
    assert captured_transitions == []


# ---------------------------------------------------------------------------
# pass path: schema_validated transition.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_validation_step_passes_when_schema_matches(
    patched_transition: None,
    captured_transitions: list[dict[str, Any]],
) -> None:
    run = _make_run()
    artifact = _make_artifact(run=run)

    result = await _make_orchestrator().execute_validation_step(
        run=run,
        artifact=artifact,
        schema=_schema_pass(),
        actor_id=uuid4(),
    )
    assert isinstance(result, ValidationStepResult)
    assert result.outcome == "schema_validated"
    assert result.to_state == "schema_validated"
    assert result.event_type == "schema_validated"
    assert result.validation_passed is True
    assert result.validation_errors == ()

    # transition_with_event was invoked exactly once with matching args
    assert len(captured_transitions) == 1
    captured = captured_transitions[0]
    assert captured["to_state"] == "schema_validated"
    assert captured["event_type"] == "schema_validated"
    assert captured["blocked_reason"] is None
    # payload carries artifact metadata, not raw content
    assert captured["payload"]["artifact_id"] == str(artifact.id)
    assert captured["payload"]["content_hash"] == artifact.content_hash
    assert captured["payload"]["payload_data_class"] == "public"


# ---------------------------------------------------------------------------
# fail path: validation_failed transition + redacted error summaries.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_validation_step_fails_when_schema_mismatch(
    patched_transition: None,
    captured_transitions: list[dict[str, Any]],
) -> None:
    run = _make_run()
    # ``summary`` too short → fails minLength
    artifact = _make_artifact(
        run=run,
        content_jsonb={"summary": "no"},
    )

    result = await _make_orchestrator().execute_validation_step(
        run=run,
        artifact=artifact,
        schema=_schema_strict_summary(),
        actor_id=uuid4(),
    )
    assert result.outcome == "validation_failed"
    assert result.to_state == "validation_failed"
    assert result.event_type == "validation_failed"
    assert result.validation_passed is False
    assert len(result.validation_errors) >= 1

    captured = captured_transitions[0]
    assert captured["to_state"] == "validation_failed"
    assert captured["event_type"] == "validation_failed"
    assert captured["payload"]["validation_error_count"] >= 1
    summaries = captured["payload"]["validation_error_summaries"]
    assert isinstance(summaries, list)
    assert all(isinstance(s, str) for s in summaries)


@pytest.mark.asyncio
async def test_execute_validation_step_redacts_instance_value_in_payload(
    patched_transition: None,
    captured_transitions: list[dict[str, Any]],
) -> None:
    """The redacted error summary must NOT echo the failing instance value
    (which could contain raw secret material from a hostile provider
    response)."""

    run = _make_run()
    hostile_value = "sk-hostile-1234567890abcdef1234567890abcdef"
    artifact = _make_artifact(
        run=run,
        # Schema expects ``summary`` to be string; we send int instead, but
        # we also fold the hostile value into a separate context to ensure
        # the redacted summary string does not echo it.
        content_jsonb={"summary": 123, "ignored": hostile_value},
    )

    await _make_orchestrator().execute_validation_step(
        run=run,
        artifact=artifact,
        schema=_schema_pass(),
        actor_id=uuid4(),
    )
    summaries = captured_transitions[0]["payload"]["validation_error_summaries"]
    for summary in summaries:
        assert hostile_value not in summary
        assert "sk-hostile" not in summary


@pytest.mark.asyncio
async def test_execute_validation_step_caps_error_summaries_at_five(
    patched_transition: None,
    captured_transitions: list[dict[str, Any]],
) -> None:
    """When more than 5 schema errors fire, the event payload includes the
    full ``validation_error_count`` but only carries the first 5 summary
    strings (defense-in-depth + payload size bound)."""

    run = _make_run()
    # Each ``properties`` value has its own ``type`` check; sending int for
    # all 10 fields produces 10 independent type errors via ``iter_errors``.
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {f"f{i}": {"type": "string"} for i in range(10)},
    }
    # Type-mismatch all 10 properties.
    content = {f"f{i}": i for i in range(10)}
    artifact = _make_artifact(run=run, content_jsonb=content)

    await _make_orchestrator().execute_validation_step(
        run=run,
        artifact=artifact,
        schema=schema,
        actor_id=uuid4(),
    )
    payload = captured_transitions[0]["payload"]
    assert payload["validation_error_count"] >= 10
    assert len(payload["validation_error_summaries"]) <= 5


# ---------------------------------------------------------------------------
# idempotency_key passthrough.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_validation_step_forwards_idempotency_key(
    patched_transition: None,
    captured_transitions: list[dict[str, Any]],
) -> None:
    run = _make_run()
    artifact = _make_artifact(run=run)
    await _make_orchestrator().execute_validation_step(
        run=run,
        artifact=artifact,
        schema=_schema_pass(),
        actor_id=uuid4(),
        idempotency_key="batch-4-test-idempotency",
    )
    captured = captured_transitions[0]
    assert captured["idempotency_key"] == "batch-4-test-idempotency"
