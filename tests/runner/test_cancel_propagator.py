"""Sprint 7 BL-0078: Runner cancel propagator (mock skeleton) tests."""

from __future__ import annotations

import pytest

from backend.app.services.runner.cancel_propagator import (
    CancelPropagator,
    CancelSignal,
    MockCancelPropagator,
)
from backend.app.services.runner.runner_adapter import RunnerCancelToken


def test_cancel_propagator_is_abc() -> None:
    """CancelPropagator は抽象 interface、直接 instantiate 不可。"""
    with pytest.raises(TypeError, match="abstract"):
        CancelPropagator()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_publish_cancel_cancels_registered_token() -> None:
    """register_token 済 token は publish_cancel で cancel される。"""
    propagator = MockCancelPropagator()
    token = RunnerCancelToken()
    await propagator.register_token("run-001", token)

    assert token.is_cancelled is False
    await propagator.publish_cancel("run-001", reason="user_request")
    assert token.is_cancelled is True


@pytest.mark.asyncio
async def test_publish_cancel_records_signal() -> None:
    """publish された signal は propagator.signals に記録される。"""
    propagator = MockCancelPropagator()
    await propagator.publish_cancel("run-001", reason="budget_blocked")

    assert len(propagator.signals) == 1
    assert propagator.signals[0].run_id == "run-001"
    assert propagator.signals[0].reason == "budget_blocked"


@pytest.mark.asyncio
async def test_late_publish_propagates_to_registered_token() -> None:
    """publish 後に register された token も signal を picked up。"""
    propagator = MockCancelPropagator()
    await propagator.publish_cancel("run-002", reason="user_request")

    token = RunnerCancelToken()
    await propagator.register_token("run-002", token)
    assert token.is_cancelled is True


@pytest.mark.asyncio
async def test_publish_does_not_affect_other_run_tokens() -> None:
    """異 run_id の token は cancel されない (boundary)."""
    propagator = MockCancelPropagator()
    token_a = RunnerCancelToken()
    token_b = RunnerCancelToken()
    await propagator.register_token("run-A", token_a)
    await propagator.register_token("run-B", token_b)

    await propagator.publish_cancel("run-A", reason="user_request")
    assert token_a.is_cancelled is True
    assert token_b.is_cancelled is False


@pytest.mark.asyncio
async def test_unregister_token() -> None:
    """unregister_token 後は publish しても token に届かない。"""
    propagator = MockCancelPropagator()
    token = RunnerCancelToken()
    await propagator.register_token("run-003", token)
    await propagator.unregister_token("run-003")

    await propagator.publish_cancel("run-003", reason="user_request")
    assert token.is_cancelled is False


def test_cancel_signal_has_default_reason() -> None:
    """CancelSignal の reason default は user_request。"""
    sig = CancelSignal(run_id="run-X")
    assert sig.reason == "user_request"
