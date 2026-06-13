"""SP-029 (ADR-00055) orchestrator ``execute_shadow_completion_step`` unit test。

shadow run は ``schema_validated -> completed`` (run_completed) で terminal 化し、
副作用 stage を一切通らない。production run がこの step を呼ぶのは設計エラー
(ValueError)。DB なし (``transition_with_event`` を monkeypatch) で step の契約を
固定する。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

import pytest

from backend.app.services.agent_runtime import orchestrator as orchestrator_module
from backend.app.services.agent_runtime.orchestrator import (
    AgentRunOrchestrator,
    ShadowCompletionStepResult,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.app.domain.provider.adapter import ProviderAdapter
    from backend.app.services.providers.compliance_gate import ComplianceGate

ACTOR_ID = UUID("00000000-0000-4000-8000-0000000029c1")


@pytest.fixture
def captured_transitions() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def patched_transition(
    monkeypatch: pytest.MonkeyPatch,
    captured_transitions: list[dict[str, Any]],
) -> None:
    async def _fake_transition_with_event(
        _session: Any,
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
            }
        )
        return SimpleNamespace(id=uuid4(), event_type=event_type, payload=payload)

    monkeypatch.setattr(
        orchestrator_module,
        "transition_with_event",
        _fake_transition_with_event,
    )


def _make_run(run_mode: str) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=1,
        project_id=uuid4(),
        status="schema_validated",
        run_mode=run_mode,
    )


def _make_orchestrator() -> AgentRunOrchestrator:
    return AgentRunOrchestrator(
        session=cast("AsyncSession", SimpleNamespace()),
        compliance_gate=cast("ComplianceGate", SimpleNamespace()),
        provider=cast("ProviderAdapter", SimpleNamespace()),
        policy_pack=None,
    )


@pytest.mark.asyncio
async def test_shadow_completion_transitions_to_completed(
    patched_transition: None,
    captured_transitions: list[dict[str, Any]],
) -> None:
    orchestrator = _make_orchestrator()
    run = _make_run("shadow")

    result = await orchestrator.execute_shadow_completion_step(
        run=run,
        actor_id=ACTOR_ID,
    )

    assert isinstance(result, ShadowCompletionStepResult)
    assert result.to_state == "completed"
    assert result.event_type == "run_completed"
    assert len(captured_transitions) == 1
    transition = captured_transitions[0]
    assert transition["to_state"] == "completed"
    assert transition["event_type"] == "run_completed"
    assert transition["payload"]["run_mode"] == "shadow"
    assert transition["payload"]["shadow_terminal"] is True


@pytest.mark.asyncio
async def test_shadow_completion_rejects_production_run(
    patched_transition: None,
    captured_transitions: list[dict[str, Any]],
) -> None:
    orchestrator = _make_orchestrator()
    run = _make_run("production")

    with pytest.raises(ValueError, match="requires run_mode='shadow'"):
        await orchestrator.execute_shadow_completion_step(
            run=run,
            actor_id=ACTOR_ID,
        )

    # production run では transition を一切発火しない (fail-fast)。
    assert captured_transitions == []


@pytest.mark.asyncio
async def test_execute_provider_step_shadow_preflight_blocks_before_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Codex R4 F-2: shadow preflight が exceeded を返すと provider.execute / compliance を
    # 一切呼ばずに blocked_budget を surface する (課金前 block)。
    from backend.app.domain.agent_runtime.budget import BudgetCheckResult

    async def fake_preflight(*_args: object, **_kwargs: object) -> BudgetCheckResult:
        return BudgetCheckResult(
            level="agent_run",
            exceeded=True,
            current_usd=None,
            hard_limit_usd=None,
            soft_threshold_usd=None,
            reason="global_kill_switch",
        )

    monkeypatch.setattr(orchestrator_module, "preflight_shadow_budget", fake_preflight)

    class _ExplodingProvider:
        def execute(self, _request: Any) -> Any:
            raise AssertionError("provider.execute must not run when preflight blocks")

    class _ExplodingGate:
        def evaluate(self, _request: Any) -> Any:
            raise AssertionError("compliance gate must not run when preflight blocks")

    run_id = uuid4()
    run = SimpleNamespace(
        id=run_id, tenant_id=1, project_id=uuid4(), status="running", run_mode="shadow"
    )
    request = SimpleNamespace(
        tenant_id=1,
        run_id=run_id,
        provider="openai",
        api_or_feature="chat",
        provider_compliance_matrix_version="2026-05-08",
    )
    orchestrator = AgentRunOrchestrator(
        session=cast("AsyncSession", SimpleNamespace()),
        compliance_gate=cast("ComplianceGate", _ExplodingGate()),
        provider=cast("ProviderAdapter", _ExplodingProvider()),
        policy_pack=None,
    )

    result = await orchestrator.execute_provider_step(
        run=cast(Any, run),
        request=cast(Any, request),
        actor_id=ACTOR_ID,
    )
    assert result.outcome == "blocked_budget"
    assert result.to_state == "blocked"
    assert result.blocked_reason == "budget_blocked"
    assert result.provider_result is None


@pytest.mark.parametrize("provider_status", ["success", "incomplete", "max_token"])
@pytest.mark.asyncio
async def test_execute_provider_step_shadow_without_usage_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    captured_transitions: list[dict[str, Any]],
    patched_transition: None,
    provider_status: str,
) -> None:
    # Codex R7/R9 F-1: shadow の provider レスポンスが usage=None なら cost 検証不能 →
    # 成功 (generated_artifact) だけでなく provider_incomplete (incomplete/max_token) でも
    # runtime_blocked で fail-closed (retry ループでの cap 迂回・課金累積防止)。
    from backend.app.domain.provider.result import ProviderResult

    async def passthrough(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(orchestrator_module, "preflight_shadow_budget", passthrough)
    monkeypatch.setattr(orchestrator_module, "preflight_shadow_request_tokens", passthrough)
    monkeypatch.setattr(
        orchestrator_module,
        "provider_request_preflight",
        lambda _request: SimpleNamespace(decision="allow", pattern_hit_kind=None),
    )

    class _Gate:
        def evaluate(self, _request: Any) -> Any:
            return SimpleNamespace(decision="allow")

    class _NoUsageProvider:
        def execute(self, _request: Any) -> ProviderResult:
            return ProviderResult(
                status=provider_status,  # type: ignore[arg-type]
                usage=None,
                model_resolved="gpt-5.5",
                api_version="v1",
                sdk_version="1.0",
                provider_request_fingerprint="a" * 64,
                redacted_response_summary={},
            )

    run_id = uuid4()
    run = SimpleNamespace(
        id=run_id, tenant_id=1, project_id=uuid4(), status="running", run_mode="shadow"
    )
    request = SimpleNamespace(
        tenant_id=1,
        run_id=run_id,
        provider="openai",
        api_or_feature="chat",
        provider_compliance_matrix_version="2026-05-08",
        max_tokens=100,
        model_dump=lambda **_kwargs: {"messages": [], "structured_output_schema": {}},
    )
    orchestrator = AgentRunOrchestrator(
        session=cast("AsyncSession", SimpleNamespace()),
        compliance_gate=cast("ComplianceGate", _Gate()),
        provider=cast("ProviderAdapter", _NoUsageProvider()),
        policy_pack=None,
    )

    result = await orchestrator.execute_provider_step(
        run=cast(Any, run),
        request=cast(Any, request),
        actor_id=ACTOR_ID,
    )
    assert result.outcome == "blocked_runtime"
    assert result.to_state == "blocked"
    assert result.blocked_reason == "runtime_blocked"
    assert captured_transitions[-1]["payload"]["reason_code"] == "shadow_usage_unverifiable"


@pytest.mark.parametrize("provider_status", ["success", "incomplete", "max_token"])
@pytest.mark.asyncio
async def test_execute_provider_step_shadow_zero_usage_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    captured_transitions: list[dict[str, Any]],
    patched_transition: None,
    provider_status: str,
) -> None:
    # Codex R13/R14 F-1: provider が usage を 0 正規化した result (tokens_input=0) は
    # **status 不問** で unverifiable として fail-closed (success / provider_incomplete とも)。
    from backend.app.domain.provider.result import ProviderResult, ProviderUsage

    async def passthrough(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(orchestrator_module, "preflight_shadow_budget", passthrough)
    monkeypatch.setattr(orchestrator_module, "preflight_shadow_request_tokens", passthrough)
    monkeypatch.setattr(
        orchestrator_module,
        "provider_request_preflight",
        lambda _request: SimpleNamespace(decision="allow", pattern_hit_kind=None),
    )

    class _Gate:
        def evaluate(self, _request: Any) -> Any:
            return SimpleNamespace(decision="allow")

    class _ZeroUsageProvider:
        def execute(self, _request: Any) -> ProviderResult:
            return ProviderResult(
                status=provider_status,  # type: ignore[arg-type]
                usage=ProviderUsage(tokens_input=0, tokens_output=0, cost_usd=0.0),
                model_resolved="gpt-5.5",
                api_version="v1",
                sdk_version="1.0",
                provider_request_fingerprint="a" * 64,
                redacted_response_summary={},
            )

    run_id = uuid4()
    run = SimpleNamespace(
        id=run_id, tenant_id=1, project_id=uuid4(), status="running", run_mode="shadow"
    )
    request = SimpleNamespace(
        tenant_id=1,
        run_id=run_id,
        provider="openai",
        api_or_feature="chat",
        provider_compliance_matrix_version="2026-05-08",
        max_tokens=100,
        model_dump=lambda **_kwargs: {"messages": [], "structured_output_schema": {}},
    )
    orchestrator = AgentRunOrchestrator(
        session=cast("AsyncSession", SimpleNamespace()),
        compliance_gate=cast("ComplianceGate", _Gate()),
        provider=cast("ProviderAdapter", _ZeroUsageProvider()),
        policy_pack=None,
    )

    result = await orchestrator.execute_provider_step(
        run=cast(Any, run),
        request=cast(Any, request),
        actor_id=ACTOR_ID,
    )
    assert result.outcome == "blocked_runtime"
    assert result.blocked_reason == "runtime_blocked"
    assert captured_transitions[-1]["payload"]["reason_code"] == "shadow_usage_unverifiable"
