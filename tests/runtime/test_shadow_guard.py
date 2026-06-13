"""SP-029 (ADR-00055) shadow_guard の副作用隔離 unit test。

shadow run (run_mode='shadow') は mutating side effect を起動できない (fail-closed)。
production run は no-op。run_mode は run object / DB row から解決し caller 申告に依存
しない (server-owned boundary)。
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.app.services.agent_runtime.shadow_guard import (
    SHADOW_SIDE_EFFECT_REASON_CODE,
    ShadowSideEffectError,
    assert_not_shadow,
    assert_run_id_not_shadow,
)

RUN_ID = UUID("00000000-0000-4000-8000-0000000029a1")
TENANT_ID = 1


def _run(run_mode: str) -> SimpleNamespace:
    return SimpleNamespace(id=RUN_ID, tenant_id=TENANT_ID, run_mode=run_mode)


class _FakeSession:
    """``scalar`` が固定の run を返す最小 fake (run_id 解決経路の検証用)。"""

    def __init__(self, run: object | None) -> None:
        self._run = run
        self.scalar_calls = 0

    async def scalar(self, _stmt: object) -> object | None:
        self.scalar_calls += 1
        return self._run


def test_assert_not_shadow_passes_for_production() -> None:
    assert_not_shadow(_run("production"), operation="approval_request_create")


def test_assert_not_shadow_raises_for_shadow() -> None:
    with pytest.raises(ShadowSideEffectError) as exc_info:
        assert_not_shadow(_run("shadow"), operation="approval_request_create")
    err = exc_info.value
    assert err.run_id == RUN_ID
    assert err.operation == "approval_request_create"
    assert err.reason_code == SHADOW_SIDE_EFFECT_REASON_CODE


def test_shadow_error_message_excludes_no_secret_but_names_operation() -> None:
    err = ShadowSideEffectError(run_id=RUN_ID, operation="repo_push")
    assert "repo_push" in str(err)
    assert SHADOW_SIDE_EFFECT_REASON_CODE in str(err)


@pytest.mark.asyncio
async def test_assert_run_id_not_shadow_raises_for_shadow_run() -> None:
    session = _FakeSession(_run("shadow"))
    with pytest.raises(ShadowSideEffectError):
        await assert_run_id_not_shadow(
            session,
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            operation="approval_request_create",
        )
    assert session.scalar_calls == 1


@pytest.mark.asyncio
async def test_assert_run_id_not_shadow_passes_for_production_run() -> None:
    session = _FakeSession(_run("production"))
    await assert_run_id_not_shadow(
        session,
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        operation="approval_request_create",
    )


@pytest.mark.asyncio
async def test_assert_run_id_not_shadow_skips_when_run_id_none() -> None:
    # run 非紐付 (ticket-level approval) は guard skip、DB 解決もしない。
    session = _FakeSession(_run("shadow"))
    await assert_run_id_not_shadow(
        session,
        tenant_id=TENANT_ID,
        run_id=None,
        operation="approval_request_create",
    )
    assert session.scalar_calls == 0


@pytest.mark.asyncio
async def test_assert_run_id_not_shadow_skips_when_run_not_found() -> None:
    # run 不在は FK / 既存 not-found 処理に委ね、guard は何もしない。
    session = _FakeSession(None)
    await assert_run_id_not_shadow(
        session,
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        operation="approval_request_create",
    )
    assert session.scalar_calls == 1
