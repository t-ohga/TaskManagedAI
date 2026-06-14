"""SP-004-5 (ADR-00057 R1-A1) enqueue dispatch contract の非 DB unit test。

worker driver は ``settings.arq_queue_name`` (default ``taskmanagedai:jobs``) を polling する。
``_enqueue_shadow_run`` が arq の default queue (``arq:queue``) に投入すると job が拾われず
permanent orphan になる (R1-A1 CRITICAL)。本 test は enqueue が **worker と同じ queue 名**に
bind されることを redis なしで固定する (create_pool / enqueue_job の両方)。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import arq
import pytest

from backend.app.config import Settings
from backend.app.mcp import api_bridge


@pytest.mark.asyncio
async def test_enqueue_shadow_run_binds_worker_queue_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    queue_name = "taskmanagedai:jobs"

    class _FakePool:
        async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> None:
            captured["function"] = function
            captured["enqueue_kwargs"] = kwargs

        async def aclose(self) -> None:
            captured["closed"] = True

    async def _fake_create_pool(_settings: Any, **kwargs: Any) -> _FakePool:
        captured["create_pool_kwargs"] = kwargs
        return _FakePool()

    # ``_enqueue_shadow_run`` は ``from arq import create_pool`` を遅延 import するため、
    # 実 arq モジュールの create_pool 属性のみ差し替える (arq.connections は維持し
    # backend.app.workers.main の import を壊さない)。
    monkeypatch.setattr(arq, "create_pool", _fake_create_pool)

    monkeypatch.setattr(
        api_bridge,
        "get_settings",
        lambda: Settings(
            database_url="postgresql+asyncpg://u:p@127.0.0.1:5432/db",
            redis_url="redis://127.0.0.1:6379/1",
            dev_login_cookie_secret="x" * 16,
            arq_queue_name=queue_name,
        ),
    )

    await api_bridge._enqueue_shadow_run(run_id=uuid4(), tenant_id=1)

    # R1-A1: enqueue_job は worker と同じ queue に _queue_name で投入する。
    assert captured["function"] == "execute_agent_run"
    assert captured["enqueue_kwargs"]["_queue_name"] == queue_name
    # keyword 引数 (R4-F2): run_id / tenant_id は keyword で渡る。
    assert "run_id" in captured["enqueue_kwargs"]
    assert "tenant_id" in captured["enqueue_kwargs"]
    # create_pool も default_queue_name を worker queue に bind する (二重防御)。
    assert captured["create_pool_kwargs"]["default_queue_name"] == queue_name
    assert captured.get("closed") is True


@pytest.mark.asyncio
async def test_enqueue_shadow_run_propagates_failure_for_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_pool が失敗したら例外を伝播する (caller の補償 queued->failed を起動するため)。"""

    async def _boom(_settings: Any, **kwargs: Any) -> SimpleNamespace:
        raise RuntimeError("redis down")

    monkeypatch.setattr(arq, "create_pool", _boom)
    monkeypatch.setattr(
        api_bridge,
        "get_settings",
        lambda: Settings(
            database_url="postgresql+asyncpg://u:p@127.0.0.1:5432/db",
            redis_url="redis://127.0.0.1:6379/1",
            dev_login_cookie_secret="x" * 16,
        ),
    )

    with pytest.raises(RuntimeError, match="redis down"):
        await api_bridge._enqueue_shadow_run(run_id=uuid4(), tenant_id=1)


@pytest.mark.asyncio
async def test_enqueue_shadow_run_swallows_close_failure_after_successful_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R8-A1: enqueue 成功後の pool.aclose() 失敗は伝播させない (dispatch failure と誤分類して
    enqueue 済 run を failed 補償しないため)。enqueue_job 自体の失敗のみ伝播する。"""
    state: dict[str, Any] = {"enqueued": False}

    class _FlakyClosePool:
        async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> None:
            state["enqueued"] = True

        async def aclose(self) -> None:
            raise RuntimeError("pool close boom")

    async def _fake_create_pool(_settings: Any, **kwargs: Any) -> _FlakyClosePool:
        return _FlakyClosePool()

    monkeypatch.setattr(arq, "create_pool", _fake_create_pool)
    monkeypatch.setattr(
        api_bridge,
        "get_settings",
        lambda: Settings(
            database_url="postgresql+asyncpg://u:p@127.0.0.1:5432/db",
            redis_url="redis://127.0.0.1:6379/1",
            dev_login_cookie_secret="x" * 16,
        ),
    )

    # enqueue は成功し close だけ失敗 → 例外を伝播させない (補償されない = run は queued のまま)。
    await api_bridge._enqueue_shadow_run(run_id=uuid4(), tenant_id=1)
    assert state["enqueued"] is True
