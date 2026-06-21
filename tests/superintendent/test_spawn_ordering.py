"""SP-PHASE1 B2: spawn ordering A-1 (pre-register -> process -> running) + compensating terminalize。

ADR-00048 §Amendment A-1 の ordering 不変を検証する (DB なし、subprocess / registry を mock):
- 順序は **latch check -> register_spawning -> process 起動 -> mark_running** で固定。
- process 起動失敗・例外時は **mark_terminal(failed)** で orphan 行を残さない (compensating path)。
- 生存 process が残れば killpg で kill する。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from backend.app.services.superintendent import agent_spawner


class _FakeProc:
    def __init__(self, pid: int = 4321, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode


class _RecordingRegistry:
    """call 順序を記録する fake registry (DB に触れない)。"""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.terminal_states: list[str] = []
        self._id = uuid4()

    async def register_spawning(self, **_: Any) -> Any:
        self.calls.append("register_spawning")
        return self._id

    async def mark_running(self, **_: Any) -> bool:
        self.calls.append("mark_running")
        return True

    async def mark_terminal(self, *, state: str, **_: Any) -> bool:
        self.calls.append("mark_terminal")
        self.terminal_states.append(state)
        return True


@pytest.fixture(autouse=True)
def _clear_active_agents() -> Any:
    agent_spawner._active_agents.clear()
    yield
    agent_spawner._active_agents.clear()


@pytest.fixture(autouse=True)
def _noop_latch(monkeypatch: pytest.MonkeyPatch) -> Any:
    """spawn ordering test は latch 挙動でなく **ordering** を検証する (B3 latch query は別 test)。

    B3 で ``_assert_not_emergency_stopped`` が DB latch query を行うようになったため、fake
    ``session=object()`` を渡す ordering test では latch を no-op に固定する。``latch_check_called_first``
    test は自前で再 monkeypatch して呼出順を観測する。
    """

    async def _noop(tenant_id: int, session: Any = None) -> None:
        return None

    monkeypatch.setattr(agent_spawner, "_assert_not_emergency_stopped", _noop)


@pytest.mark.asyncio
async def test_spawn_managed_orders_register_then_process_then_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _RecordingRegistry()
    order: list[str] = []

    async def _fake_start(provider: str, project_dir: str) -> _FakeProc:
        order.append("process_started")
        return _FakeProc()

    monkeypatch.setattr(agent_spawner, "_start_subprocess", _fake_start)
    monkeypatch.setattr(agent_spawner.os, "getpgid", lambda _pid: 4321)
    monkeypatch.setattr(agent_spawner, "get_host_boot_id", lambda: "boot-xyz")

    agent_id = uuid4()
    project_id = uuid4()
    await agent_spawner.spawn_agent_managed(
        agent_id=agent_id,
        provider="custom",
        project_dir="/tmp/proj",  # noqa: S108 - test fixture path
        tenant_id=1,
        project_id=project_id,
        registry=registry,  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        host_id="host-1",
    )

    # 順序固定: register_spawning は process 起動より前、mark_running は process 起動より後。
    assert registry.calls == ["register_spawning", "mark_running"]
    assert order == ["process_started"]
    assert "mark_terminal" not in registry.calls
    # in-process cache に登録される (process-local handle)。
    assert agent_id in agent_spawner._active_agents


@pytest.mark.asyncio
async def test_spawn_managed_compensating_terminalize_on_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _RecordingRegistry()

    async def _failing_start(provider: str, project_dir: str) -> _FakeProc:
        raise RuntimeError("exec failed")

    monkeypatch.setattr(agent_spawner, "_start_subprocess", _failing_start)

    agent_id = uuid4()
    with pytest.raises(RuntimeError, match="exec failed"):
        await agent_spawner.spawn_agent_managed(
            agent_id=agent_id,
            provider="custom",
            project_dir="/tmp/proj",  # noqa: S108 - test fixture path
            tenant_id=1,
            project_id=uuid4(),
            registry=registry,  # type: ignore[arg-type]
            session=object(),  # type: ignore[arg-type]
            host_id="host-1",
        )

    # pre-register 後に起動失敗 → compensating terminalize で failed 化 (orphan 行なし)。
    assert registry.calls == ["register_spawning", "mark_terminal"]
    assert registry.terminal_states == ["failed"]
    # 起動失敗なので in-process cache には登録されない。
    assert agent_id not in agent_spawner._active_agents


@pytest.mark.asyncio
async def test_spawn_managed_killpg_and_terminalize_when_mark_running_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """process は起動したが mark_running 中に例外 → 生存 process を killpg + terminalize。"""
    registry = _RecordingRegistry()
    proc = _FakeProc(pid=9999, returncode=None)
    killpg_targets: list[int] = []

    async def _fake_start(provider: str, project_dir: str) -> _FakeProc:
        return proc

    async def _boom_mark_running(**_: Any) -> bool:
        registry.calls.append("mark_running")
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(agent_spawner, "_start_subprocess", _fake_start)
    monkeypatch.setattr(agent_spawner.os, "getpgid", lambda _pid: 9999)
    monkeypatch.setattr(agent_spawner, "get_host_boot_id", lambda: "boot-xyz")
    monkeypatch.setattr(
        agent_spawner.os, "killpg", lambda pgid, _sig: killpg_targets.append(pgid)
    )
    registry.mark_running = _boom_mark_running  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="db hiccup"):
        await agent_spawner.spawn_agent_managed(
            agent_id=uuid4(),
            provider="custom",
            project_dir="/tmp/proj",  # noqa: S108 - test fixture path
            tenant_id=1,
            project_id=uuid4(),
            registry=registry,  # type: ignore[arg-type]
            session=object(),  # type: ignore[arg-type]
            host_id="host-1",
        )

    assert registry.calls == ["register_spawning", "mark_running", "mark_terminal"]
    assert registry.terminal_states == ["failed"]
    # 生存 process は killpg された (orphan process を残さない)。
    assert killpg_targets == [9999]


@pytest.mark.asyncio
async def test_spawn_managed_killpg_and_aborts_when_mark_running_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MEDIUM-2: mark_running が False (concurrent terminalize で spawning 行が既に terminal) を返したら、
    起動済み live process を killpg + _active_agents 非登録 + 例外 raise (unkillable orphan を作らない)。
    """
    registry = _RecordingRegistry()
    proc = _FakeProc(pid=7777, returncode=None)
    killpg_targets: list[int] = []
    agent_id = uuid4()

    async def _fake_start(provider: str, project_dir: str) -> _FakeProc:
        return proc

    async def _false_mark_running(**_: Any) -> bool:
        registry.calls.append("mark_running")
        return False  # spawning 行が concurrent terminalize 済み (rowcount=0)

    monkeypatch.setattr(agent_spawner, "_start_subprocess", _fake_start)
    monkeypatch.setattr(agent_spawner.os, "getpgid", lambda _pid: 7777)
    monkeypatch.setattr(agent_spawner, "get_host_boot_id", lambda: "boot-xyz")
    monkeypatch.setattr(
        agent_spawner.os, "killpg", lambda pgid, _sig: killpg_targets.append(pgid)
    )
    registry.mark_running = _false_mark_running  # type: ignore[method-assign]

    with pytest.raises(agent_spawner.ManagedAgentTerminalizedDuringSpawn):
        await agent_spawner.spawn_agent_managed(
            agent_id=agent_id,
            provider="custom",
            project_dir="/tmp/proj",  # noqa: S108 - test fixture path
            tenant_id=1,
            project_id=uuid4(),
            registry=registry,  # type: ignore[arg-type]
            session=object(),  # type: ignore[arg-type]
            host_id="host-1",
        )

    # live process を始末 (killpg) + compensating terminalize、in-process 非登録。
    assert killpg_targets == [7777]
    assert registry.calls == ["register_spawning", "mark_running", "mark_terminal"]
    assert registry.terminal_states == ["failed"]
    assert agent_id not in agent_spawner._active_agents


@pytest.mark.asyncio
async def test_spawn_managed_latch_check_called_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """latch check (_assert_not_emergency_stopped) は register_spawning より前に呼ばれる。

    B3 が latch 本体を実装すると engaged tenant の spawn は register 前に abort する (A-1 §1)。
    """
    registry = _RecordingRegistry()
    seq: list[str] = []

    async def _latch(tenant_id: int, session: Any = None) -> None:
        seq.append("latch_check")

    async def _fake_start(provider: str, project_dir: str) -> _FakeProc:
        return _FakeProc()

    original_register = registry.register_spawning

    async def _tracking_register(**kwargs: Any) -> Any:
        seq.append("register")
        return await original_register(**kwargs)

    monkeypatch.setattr(agent_spawner, "_assert_not_emergency_stopped", _latch)
    monkeypatch.setattr(agent_spawner, "_start_subprocess", _fake_start)
    monkeypatch.setattr(agent_spawner.os, "getpgid", lambda _pid: 1)
    monkeypatch.setattr(agent_spawner, "get_host_boot_id", lambda: None)
    registry.register_spawning = _tracking_register  # type: ignore[method-assign]

    await agent_spawner.spawn_agent_managed(
        agent_id=uuid4(),
        provider="custom",
        project_dir="/tmp/proj",  # noqa: S108 - test fixture path
        tenant_id=1,
        project_id=uuid4(),
        registry=registry,  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        host_id="host-1",
    )

    assert seq[0] == "latch_check"
    assert seq.index("latch_check") < seq.index("register")
