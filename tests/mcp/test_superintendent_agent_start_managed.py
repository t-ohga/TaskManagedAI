"""SP-PHASE1 B4 (P1-1 fix): MCP ``superintendent_agent_start`` → ``spawn_agent_managed`` 移行 unit test。

legacy ``spawn_agent`` (sessionless、latch 未確認 = fail-open) から ``spawn_agent_managed`` (latch
fail-closed deny + managed_agents 登録) への移行を検証する (DB なし、context / spawner を mock):

- managed spawn 経由で起動する (legacy spawn_agent を呼ばない)。
- latch engaged 中は ``state='denied' / error='emergency_stop_engaged'`` (fail-closed deny、P1-1 解消)。
- sessionless (DB session 取得失敗) は ``state='failed'`` (latch 確認不能 = 起動拒否)。
- 不存在 / cross-tenant project_id は ``state='denied' / error='project_not_found'``。
- invalid provider / invalid uuid は DB に触れる前に reject。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest

from backend.app.mcp import server as mcp_server
from backend.app.services.superintendent import agent_spawner
from backend.app.services.superintendent.agent_spawner import SpawnedAgent
from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

PROJECT_ID = "00000000-0000-4000-8000-000000000004"


class _FakeSession:
    def __init__(self, *, project_found: bool = True) -> None:
        self._project_found = project_found
        self.committed = False
        self.rolled_back = False

    async def scalar(self, _stmt: Any) -> Any:
        # project existence query。found なら project_id を返す、不存在は None。
        return uuid4() if self._project_found else None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def _patch_get_db_session(
    monkeypatch: pytest.MonkeyPatch, session: _FakeSession | None
) -> None:
    """``get_db_session`` を fake session の async context manager に差し替える。

    session=None なら session 取得失敗 (sessionless) を模す。
    """
    from backend.app.mcp import context as mcp_context

    @asynccontextmanager
    async def _fake_ctx() -> AsyncIterator[Any]:
        if session is None:
            raise RuntimeError("db session unavailable")
        yield session

    monkeypatch.setattr(mcp_context, "get_db_session", _fake_ctx)


@pytest.mark.asyncio
async def test_agent_start_uses_managed_spawn_not_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """managed spawn 経由で起動し、legacy spawn_agent は呼ばれない (P1-1 解消)。"""
    session = _FakeSession(project_found=True)
    _patch_get_db_session(monkeypatch, session)

    managed_calls: list[dict[str, Any]] = []
    legacy_calls: list[Any] = []

    async def _fake_managed(**kwargs: Any) -> SpawnedAgent:
        managed_calls.append(kwargs)
        return SpawnedAgent(agent_id=kwargs["agent_id"], provider="claude", pid=4242)

    async def _fake_legacy(*args: Any, **kwargs: Any) -> SpawnedAgent:
        legacy_calls.append((args, kwargs))
        return SpawnedAgent(agent_id=uuid4(), provider="claude", pid=1)

    monkeypatch.setattr(agent_spawner, "spawn_agent_managed", _fake_managed)
    monkeypatch.setattr(agent_spawner, "spawn_agent", _fake_legacy)

    agent_id = str(uuid4())
    result = await mcp_server.superintendent_agent_start(
        agent_id=agent_id, provider="claude", project_id=PROJECT_ID
    )

    assert result["state"] == "starting"
    assert result["pid"] == 4242
    assert len(managed_calls) == 1
    assert legacy_calls == []
    # commit 境界: managed spawn は commit しない → tool が commit する (A-1)。
    assert session.committed is True


@pytest.mark.asyncio
async def test_agent_start_denied_when_latch_engaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """latch engaged 中は fail-closed deny (P1-1 解消、新規活動を起動しない)。"""
    session = _FakeSession(project_found=True)
    _patch_get_db_session(monkeypatch, session)

    async def _engaged_managed(**kwargs: Any) -> SpawnedAgent:
        raise EmergencyStopEngagedError(tenant_id=1)

    monkeypatch.setattr(agent_spawner, "spawn_agent_managed", _engaged_managed)

    result = await mcp_server.superintendent_agent_start(
        agent_id=str(uuid4()), provider="claude", project_id=PROJECT_ID
    )
    assert result["state"] == "denied"
    assert result["error"] == "emergency_stop_engaged"
    assert session.rolled_back is True
    assert session.committed is False


@pytest.mark.asyncio
async def test_agent_start_sessionless_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB session 取得失敗 (sessionless) は起動拒否 (latch 確認不能 = fail-closed)。"""
    _patch_get_db_session(monkeypatch, None)

    spawned: list[Any] = []

    async def _fake_managed(**kwargs: Any) -> SpawnedAgent:
        spawned.append(kwargs)
        return SpawnedAgent(agent_id=kwargs["agent_id"], provider="claude", pid=1)

    monkeypatch.setattr(agent_spawner, "spawn_agent_managed", _fake_managed)

    result = await mcp_server.superintendent_agent_start(
        agent_id=str(uuid4()), provider="claude", project_id=PROJECT_ID
    )
    # session 取得失敗 → spawn は試行されず failed (起動しない)。
    assert result["state"] == "failed"
    assert spawned == []


@pytest.mark.asyncio
async def test_agent_start_unknown_project_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不存在 / cross-tenant project_id は deny (spawn しない)。"""
    session = _FakeSession(project_found=False)
    _patch_get_db_session(monkeypatch, session)

    spawned: list[Any] = []

    async def _fake_managed(**kwargs: Any) -> SpawnedAgent:
        spawned.append(kwargs)
        return SpawnedAgent(agent_id=kwargs["agent_id"], provider="claude", pid=1)

    monkeypatch.setattr(agent_spawner, "spawn_agent_managed", _fake_managed)

    result = await mcp_server.superintendent_agent_start(
        agent_id=str(uuid4()), provider="claude", project_id=PROJECT_ID
    )
    assert result["state"] == "denied"
    assert result["error"] == "project_not_found"
    assert spawned == []


@pytest.mark.asyncio
async def test_agent_start_invalid_provider_rejected_before_db() -> None:
    result = await mcp_server.superintendent_agent_start(
        agent_id=str(uuid4()), provider="evil", project_id=PROJECT_ID
    )
    assert result == {"error": "invalid_provider", "valid": ["claude", "codex", "custom"]}


@pytest.mark.asyncio
async def test_agent_start_invalid_uuid_rejected_before_db() -> None:
    result = await mcp_server.superintendent_agent_start(
        agent_id="not-a-uuid", provider="claude", project_id=PROJECT_ID
    )
    assert result["state"] == "failed"
    assert result["error"] == "invalid_uuid"


class _CommitFailSession(_FakeSession):
    """commit が freeze gate 等で reject される session (LOW-4)。"""

    async def commit(self) -> None:
        raise RuntimeError("freeze gate rejected commit")


class _FakeProc:
    def __init__(self, pid: int = 9191) -> None:
        self.pid = pid
        self.returncode = None


@pytest.mark.asyncio
async def test_agent_start_kills_orphan_on_commit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOW-4: commit 失敗 (freeze gate reject) で起動済 live subprocess を killpg で kill する。"""
    session = _CommitFailSession(project_found=True)
    _patch_get_db_session(monkeypatch, session)

    live_proc = _FakeProc(pid=9191)

    async def _fake_managed(**kwargs: Any) -> SpawnedAgent:
        # spawn 成功 (live process 付き) を返す。
        return SpawnedAgent(
            agent_id=kwargs["agent_id"], provider="claude", pid=9191, process=live_proc  # type: ignore[arg-type]
        )

    monkeypatch.setattr(agent_spawner, "spawn_agent_managed", _fake_managed)

    killpg_targets: list[int] = []
    monkeypatch.setattr(mcp_server.os, "getpgid", lambda _pid: 9191)
    monkeypatch.setattr(
        mcp_server.os, "killpg", lambda pgid, _sig: killpg_targets.append(pgid)
    )

    result = await mcp_server.superintendent_agent_start(
        agent_id=str(uuid4()), provider="claude", project_id=PROJECT_ID
    )
    # commit 失敗 → outer except で failed、かつ orphan live process を killpg で kill。
    assert result["state"] == "failed"
    assert killpg_targets == [9191]
    assert session.rolled_back is True
