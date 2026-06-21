"""SP-PHASE1 B4: cross-process kill hybrid supervisor (ADR-00048 §F / §Amendment A-2) unit test。

CI で実 subprocess を spawn せずに以下を検証する (os.killpg / registry / latch は mock):
- ``kill_managed_agents_on_host``: 当該 host+tenant の running 行のみ killpg + mark_terminal(stopped)。
  別 host / boot_id 不一致 / spawning (pgid 未確定) を skip (negative)。
- ``_killable`` / ``_started_at_consistent``: host scope + boot_id + started_at の三重防御。
- ``supervisor_poll_once``: engaged tenant のみ kill (非 engaged tenant は触らない、tenant scope LOW-3)。
- ``EmergencyStopSupervisor``: wake (pub/sub) / poll (timeout) hybrid loop が engage を検出して kill。
  Redis 障害でも DB poll fallback で動く (fail-closed)。

実 subprocess + 2 process 協調の cross-process kill 実証は CI 不可 → operator/integration test として
本 module 末尾 ``test_cross_process_kill_operator_run`` の docstring に手順明記 (B6 exit / 実機検証)。
"""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from backend.app.services.superintendent import supervisor as sup
from backend.app.services.superintendent.managed_agent_registry import ManagedAgentView

HOST_A = "host-a"
HOST_B = "host-b"
BOOT_X = "boot-x"
BOOT_Y = "boot-y"


def _view(
    *,
    host_id: str = HOST_A,
    pgid: int | None = 4321,
    pid: int | None = 4321,
    state: str = "running",
    boot_id: str | None = BOOT_X,
    tenant_id: int = 1,
    started_at: datetime | None = None,
) -> ManagedAgentView:
    return ManagedAgentView(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=uuid4(),
        agent_run_id=None,
        host_id=host_id,
        process_group_id=pgid,
        pid=pid,
        supervisor_id=None,
        state=state,  # type: ignore[arg-type]
        boot_id=boot_id,
        started_at=started_at,
    )


class _FakeRegistry:
    """list_active_on_host + mark_terminal を記録する fake registry (DB に触れない)。"""

    def __init__(self, rows: list[ManagedAgentView]) -> None:
        self._rows = rows
        self.terminalized: list[Any] = []

    async def list_active_on_host(
        self,
        *,
        host_id: str,
        tenant_id: int | None = None,
        for_update_skip_locked: bool = False,
    ) -> list[ManagedAgentView]:
        return [
            r
            for r in self._rows
            if r.host_id == host_id and (tenant_id is None or r.tenant_id == tenant_id)
        ]

    async def mark_terminal(
        self, *, tenant_id: int, managed_agent_id: Any, state: str
    ) -> bool:
        self.terminalized.append((tenant_id, managed_agent_id, state))
        return True


# --- _killable ---


def test_killable_same_host_boot_ok() -> None:
    assert sup._killable(_view(), host_id=HOST_A, host_boot_id=BOOT_X) is True


def test_killable_rejects_other_host() -> None:
    assert sup._killable(_view(host_id=HOST_B), host_id=HOST_A, host_boot_id=BOOT_X) is False


def test_killable_rejects_boot_id_mismatch() -> None:
    assert sup._killable(_view(boot_id=BOOT_Y), host_id=HOST_A, host_boot_id=BOOT_X) is False


def test_killable_rejects_none_pgid() -> None:
    assert sup._killable(_view(pgid=None), host_id=HOST_A, host_boot_id=BOOT_X) is False


def test_killable_allows_when_row_boot_none_best_effort() -> None:
    # 旧 row (boot_id None) は best-effort で許可 (host scope が主防御)。
    assert sup._killable(_view(boot_id=None), host_id=HOST_A, host_boot_id=BOOT_X) is True


# --- _started_at_consistent (psutil 不在環境では best-effort True) ---


def test_started_at_consistent_no_started_at_is_best_effort_true() -> None:
    assert sup._started_at_consistent(_view(started_at=None)) is True


def test_started_at_consistent_no_pid_is_best_effort_true() -> None:
    assert sup._started_at_consistent(_view(pid=None, started_at=datetime.now(UTC))) is True


def test_started_at_consistent_unavailable_proc_time_is_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sup, "_proc_started_at", lambda _pid: None)
    assert sup._started_at_consistent(_view(started_at=datetime.now(UTC))) is True


def test_started_at_consistent_match_within_tolerance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    monkeypatch.setattr(sup, "_proc_started_at", lambda _pid: now + timedelta(seconds=2))
    assert sup._started_at_consistent(_view(started_at=now)) is True


def test_started_at_consistent_rejects_pid_reuse(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    # pid 起動時刻が DB row started_at と大きく乖離 = pid 再利用 (別 process) → False (signal しない)。
    monkeypatch.setattr(sup, "_proc_started_at", lambda _pid: now + timedelta(hours=1))
    assert sup._started_at_consistent(_view(started_at=now)) is False


# --- kill_managed_agents_on_host ---


@pytest.mark.asyncio
async def test_kill_managed_agents_kills_running_and_terminalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed_pgids: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: killed_pgids.append(pgid))
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)

    row = _view(pgid=4321)
    registry = _FakeRegistry([row])
    killed = await sup.kill_managed_agents_on_host(
        registry=registry, tenant_id=1, host_id=HOST_A  # type: ignore[arg-type]
    )
    assert [v.id for v in killed] == [row.id]
    assert killed_pgids == [4321]
    assert registry.terminalized == [(1, row.id, "stopped")]


@pytest.mark.asyncio
async def test_kill_managed_agents_skips_other_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed_pgids: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: killed_pgids.append(pgid))
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)

    # registry は host scope で絞るため別 host 行は列挙されない (二重防御も _killable で確認)。
    registry = _FakeRegistry([_view(host_id=HOST_B, pgid=9999)])
    killed = await sup.kill_managed_agents_on_host(
        registry=registry, tenant_id=1, host_id=HOST_A  # type: ignore[arg-type]
    )
    assert killed == []
    assert killed_pgids == []
    assert registry.terminalized == []


@pytest.mark.asyncio
async def test_kill_managed_agents_skips_boot_id_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed_pgids: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: killed_pgids.append(pgid))
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)

    registry = _FakeRegistry([_view(boot_id=BOOT_Y, pgid=4321)])
    killed = await sup.kill_managed_agents_on_host(
        registry=registry, tenant_id=1, host_id=HOST_A  # type: ignore[arg-type]
    )
    assert killed == []
    assert killed_pgids == []


@pytest.mark.asyncio
async def test_kill_managed_agents_skips_spawning_pgid_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pgid 未確定 (spawning) 行は kill skip + terminalize しない (次 poll で再評価)。"""
    killed_pgids: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: killed_pgids.append(pgid))
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)

    registry = _FakeRegistry([_view(pgid=None, pid=None, state="spawning")])
    killed = await sup.kill_managed_agents_on_host(
        registry=registry, tenant_id=1, host_id=HOST_A  # type: ignore[arg-type]
    )
    assert killed == []
    assert killed_pgids == []
    # spawning は terminalize もしない (running 化後に kill されるべき)。
    assert registry.terminalized == []


@pytest.mark.asyncio
async def test_kill_managed_agents_terminalizes_even_if_process_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """既に消滅 (killpg が ProcessLookupError) でも DB 行は terminalize する (registry 整合)。"""

    def _dead_killpg(_pgid: int, _sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(sup.os, "killpg", _dead_killpg)
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)

    row = _view(pgid=4321)
    registry = _FakeRegistry([row])
    killed = await sup.kill_managed_agents_on_host(
        registry=registry, tenant_id=1, host_id=HOST_A  # type: ignore[arg-type]
    )
    assert [v.id for v in killed] == [row.id]
    assert registry.terminalized == [(1, row.id, "stopped")]


@pytest.mark.asyncio
async def test_kill_managed_agents_does_not_terminalize_unkillable_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H2: EPERM (生存だが signal 不能) は terminalize しない (fail-open 防止、次 poll で retry)。"""

    def _eperm_killpg(_pgid: int, _sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(sup.os, "killpg", _eperm_killpg)
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)

    row = _view(pgid=4321)
    registry = _FakeRegistry([row])
    killed = await sup.kill_managed_agents_on_host(
        registry=registry, tenant_id=1, host_id=HOST_A  # type: ignore[arg-type]
    )
    # 生存 un-killable は killed に数えず、terminalize もしない (stopped 誤記録しない)。
    assert killed == []
    assert registry.terminalized == []


def test_killpg_outcome_classifies_eperm_as_still_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _eperm(_pgid: int, _sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(sup.os, "killpg", _eperm)
    assert sup._killpg(_view(pgid=1)) is sup._KillOutcome.STILL_ALIVE


def test_killpg_outcome_classifies_processlookup_as_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _gone(_pgid: int, _sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(sup.os, "killpg", _gone)
    assert sup._killpg(_view(pgid=1)) is sup._KillOutcome.ALREADY_GONE


def test_killpg_outcome_classifies_success_as_killed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sup.os, "killpg", lambda _pgid, _sig: None)
    assert sup._killpg(_view(pgid=1)) is sup._KillOutcome.KILLED


def test_killpg_outcome_pgid_none_is_gone() -> None:
    assert sup._killpg(_view(pgid=None)) is sup._KillOutcome.ALREADY_GONE


def test_killpg_refuses_zero_pgid_without_calling_killpg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HIGH-2: pgid=0 は killpg(0) = supervisor self-kill。killpg を呼ばず STILL_ALIVE で skip。"""
    called: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: called.append(pgid))
    assert sup._killpg(_view(pgid=0)) is sup._KillOutcome.STILL_ALIVE
    assert called == []  # killpg は **呼ばれない** (self-kill 回避)。


def test_killpg_refuses_negative_pgid_without_calling_killpg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HIGH-2: 負 pgid も POSIX kill 特殊指定。killpg を呼ばず STILL_ALIVE で skip。"""
    called: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: called.append(pgid))
    assert sup._killpg(_view(pgid=-1)) is sup._KillOutcome.STILL_ALIVE
    assert called == []


@pytest.mark.asyncio
async def test_kill_managed_agents_does_not_terminalize_zero_pgid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HIGH-2: 0/負 pgid 行は STILL_ALIVE 扱いで terminalize しない (誤 stopped 記録しない)。"""
    called: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: called.append(pgid))
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)
    registry = _FakeRegistry([_view(pgid=0)])
    killed = await sup.kill_managed_agents_on_host(
        registry=registry, tenant_id=1, host_id=HOST_A  # type: ignore[arg-type]
    )
    assert killed == []
    assert called == []
    assert registry.terminalized == []


@pytest.mark.asyncio
async def test_kill_managed_agents_requests_skip_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H1: active 行列挙は FOR UPDATE SKIP LOCKED で行う (2 supervisor 並走で二重 signal 防止)。"""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(sup.os, "killpg", lambda _pgid, _sig: None)
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)

    class _LockAwareRegistry(_FakeRegistry):
        async def list_active_on_host(  # type: ignore[override]
            self, *, host_id: str, tenant_id: int | None = None,
            for_update_skip_locked: bool = False,
        ) -> list[ManagedAgentView]:
            captured["skip_locked"] = for_update_skip_locked
            return await super().list_active_on_host(host_id=host_id, tenant_id=tenant_id)

    registry = _LockAwareRegistry([_view(pgid=4321)])
    await sup.kill_managed_agents_on_host(
        registry=registry, tenant_id=1, host_id=HOST_A  # type: ignore[arg-type]
    )
    assert captured["skip_locked"] is True


@pytest.mark.asyncio
async def test_kill_managed_agents_signal_uses_sigkill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda _pgid, sig: signals.append(sig))
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)
    registry = _FakeRegistry([_view(pgid=4321)])
    await sup.kill_managed_agents_on_host(
        registry=registry, tenant_id=1, host_id=HOST_A  # type: ignore[arg-type]
    )
    assert signals == [signal.SIGKILL]


# --- supervisor_poll_once (tenant scope) ---


@pytest.fixture(autouse=True)
def _patch_bypass(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """MEDIUM-3: supervisor_poll_once が呼ぶ mark_emergency_stop_bypass を記録 fake に差し替える。

    実 ``mark_emergency_stop_bypass`` は AsyncSession を要求するため、fake session を使う poll test では
    no-op fake に差し替えつつ「呼ばれたか」を記録する。
    """
    import backend.app.db.active_registry_mutation_gate as gate_mod

    calls: list[object] = []

    def _fake_bypass(session: object) -> None:
        calls.append(session)

    monkeypatch.setattr(gate_mod, "mark_emergency_stop_bypass", _fake_bypass)
    return calls


class _FakeSession:
    def __init__(self, engaged_tenants: list[int]) -> None:
        self._engaged = engaged_tenants
        self.committed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def scalars(self, _stmt: Any) -> Any:
        engaged = self._engaged

        class _Result:
            @staticmethod
            def all() -> list[int]:
                return engaged

        return _Result()

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_poll_once_kills_only_engaged_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engaged tenant (1) の自 host 行だけ kill。非 engaged tenant (2) は触らない (tenant scope)。"""
    killed_pgids: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: killed_pgids.append(pgid))
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)

    rows = [
        _view(tenant_id=1, pgid=111),  # engaged tenant → kill
        _view(tenant_id=2, pgid=222),  # 非 engaged → 触らない
    ]

    # session_factory: latch session は engaged=[1]、kill session は registry を rows で構成。
    def _factory() -> _FakeSession:
        return _FakeSession(engaged_tenants=[1])

    # ManagedAgentRegistry を fake に差し替え (kill session 用)。
    fake_reg = _FakeRegistry(rows)
    monkeypatch.setattr(sup, "ManagedAgentRegistry", lambda _session: fake_reg)

    killed = await sup.supervisor_poll_once(
        session_factory=_factory, host_id=HOST_A  # type: ignore[arg-type]
    )
    # tenant 1 の pgid 111 のみ kill (tenant 2 の 222 は engaged でないため列挙されない)。
    assert killed_pgids == [111]
    assert [v.process_group_id for v in killed] == [111]


@pytest.mark.asyncio
async def test_poll_once_no_engaged_tenant_no_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed_pgids: list[int] = []
    monkeypatch.setattr(sup.os, "killpg", lambda pgid, _sig: killed_pgids.append(pgid))
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)
    monkeypatch.setattr(sup, "ManagedAgentRegistry", lambda _session: _FakeRegistry([]))

    def _factory() -> _FakeSession:
        return _FakeSession(engaged_tenants=[])

    killed = await sup.supervisor_poll_once(
        session_factory=_factory, host_id=HOST_A  # type: ignore[arg-type]
    )
    assert killed == []
    assert killed_pgids == []


@pytest.mark.asyncio
async def test_poll_once_marks_freeze_gate_bypass_for_kill_session(
    monkeypatch: pytest.MonkeyPatch,
    _patch_bypass: list[object],
) -> None:
    """MEDIUM-3: kill session は freeze gate bypass を mark される (freeze 中も terminalize 永続化)。"""
    monkeypatch.setattr(sup.os, "killpg", lambda _pgid, _sig: None)
    monkeypatch.setattr(sup, "get_host_boot_id", lambda: BOOT_X)
    monkeypatch.setattr(
        sup, "ManagedAgentRegistry", lambda _session: _FakeRegistry([_view(pgid=111)])
    )

    def _factory() -> _FakeSession:
        return _FakeSession(engaged_tenants=[1])

    await sup.supervisor_poll_once(
        session_factory=_factory, host_id=HOST_A  # type: ignore[arg-type]
    )
    # engaged tenant 1 の kill session で bypass が 1 回 mark された。
    assert len(_patch_bypass) == 1


# --- EmergencyStopSupervisor hybrid loop ---


class _FakePubSub:
    """1 件の wake message を返し、以降は timeout (None) を返す fake pubsub。"""

    def __init__(self, messages: list[object | None]) -> None:
        self._messages = list(messages)
        self.subscribed: list[str] = []
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        self.subscribed.extend(channels)

    async def get_message(
        self, ignore_subscribe_messages: bool = True, **_: object
    ) -> object | None:
        if self._messages:
            return self._messages.pop(0)
        # 残りは即 None (timeout 相当)。loop 暴走を避けるため少し待つ。
        await asyncio.sleep(0.01)
        return None

    async def aclose(self) -> None:
        self.closed = True


class _FakeRedis:
    def __init__(self, pubsub: _FakePubSub) -> None:
        self._pubsub = pubsub

    def pubsub(self) -> _FakePubSub:
        return self._pubsub


@pytest.mark.asyncio
async def test_supervisor_loop_wake_triggers_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """wake message 受信で poll (kill) が呼ばれる (即時 wake path)。"""
    poll_calls: list[int] = []

    async def _fake_poll_once(*, session_factory: Any, host_id: str) -> list[Any]:
        poll_calls.append(1)
        return []

    monkeypatch.setattr(sup, "supervisor_poll_once", _fake_poll_once)

    pubsub = _FakePubSub(messages=[{"type": "message", "data": "wake"}])
    supervisor = sup.EmergencyStopSupervisor(
        session_factory=lambda: None,  # type: ignore[arg-type,return-value]
        host_id=HOST_A,
        redis_factory=lambda: _FakeRedis(pubsub),
        poll_interval=0.05,
    )
    task = asyncio.create_task(supervisor.run())
    await asyncio.sleep(0.15)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=2.0)

    assert pubsub.subscribed == [sup.SUPERVISOR_WAKE_CHANNEL]
    # 起動直後 poll (1) + wake poll (1) + poll_interval timeout poll 1+ → 2 以上。
    assert len(poll_calls) >= 2
    assert pubsub.closed is True


@pytest.mark.asyncio
async def test_supervisor_loop_polls_without_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis factory 無し (degraded) でも poll_interval 毎に DB poll する (fail-closed fallback)。"""
    poll_calls: list[int] = []

    async def _fake_poll_once(*, session_factory: Any, host_id: str) -> list[Any]:
        poll_calls.append(1)
        return []

    monkeypatch.setattr(sup, "supervisor_poll_once", _fake_poll_once)

    supervisor = sup.EmergencyStopSupervisor(
        session_factory=lambda: None,  # type: ignore[arg-type,return-value]
        host_id=HOST_A,
        redis_factory=None,
        poll_interval=0.03,
    )
    task = asyncio.create_task(supervisor.run())
    await asyncio.sleep(0.12)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=2.0)
    # 起動直後 + 複数 timeout poll。
    assert len(poll_calls) >= 2


@pytest.mark.asyncio
async def test_supervisor_loop_redis_subscribe_failure_degrades_to_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis subscribe が例外を投げても DB poll fallback で動く (fail-closed)。"""
    poll_calls: list[int] = []

    async def _fake_poll_once(*, session_factory: Any, host_id: str) -> list[Any]:
        poll_calls.append(1)
        return []

    monkeypatch.setattr(sup, "supervisor_poll_once", _fake_poll_once)

    def _boom_factory() -> Any:
        raise RuntimeError("redis down")

    supervisor = sup.EmergencyStopSupervisor(
        session_factory=lambda: None,  # type: ignore[arg-type,return-value]
        host_id=HOST_A,
        redis_factory=_boom_factory,
        poll_interval=0.03,
    )
    task = asyncio.create_task(supervisor.run())
    await asyncio.sleep(0.12)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=2.0)
    assert len(poll_calls) >= 2


@pytest.mark.asyncio
async def test_supervisor_loop_poll_exception_does_not_kill_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """poll 内例外で loop が死なない (安全機能は例外で停止しない)。"""
    calls: list[int] = []

    async def _boom_poll(*, session_factory: Any, host_id: str) -> list[Any]:
        calls.append(1)
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(sup, "supervisor_poll_once", _boom_poll)

    supervisor = sup.EmergencyStopSupervisor(
        session_factory=lambda: None,  # type: ignore[arg-type,return-value]
        host_id=HOST_A,
        redis_factory=None,
        poll_interval=0.03,
    )
    task = asyncio.create_task(supervisor.run())
    await asyncio.sleep(0.12)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=2.0)
    # 例外が起きても複数回 poll を試み続ける (loop alive)。
    assert len(calls) >= 2


def test_cross_process_kill_operator_run() -> None:
    """**operator/integration test (CI 不可、実機検証 / B6 exit verification 用の手順記載)**。

    実 subprocess を MCP 経由 spawn → FastAPI endpoint engage → supervisor が killpg で実 process kill、
    を実機確認する。real process + 2 process (FastAPI / MCP) 協調が要り CI 不可のため手順のみ記載する。

    前提:
      - throwaway PostgreSQL + Redis を起動 (例: port 15435 / 16379)。alembic upgrade head 済。
      - 同一 host で (a) FastAPI process、(b) MCP server process (supervisor loop 配線済) を起動する
        (A-2「同一 host の supervisor のみ kill」のため両者は同 host)。

    手順:
      1. MCP ``superintendent_agent_register`` → ``superintendent_agent_start(agent_id, provider,
         project_id)`` で agent subprocess を spawn する。``managed_agents`` に host_id/pgid/state=running
         行が登録されることを ``select * from managed_agents where state='running'`` で確認。
      2. spawn された subprocess の pgid を ``ps -o pgid= -p <pid>`` で確認 (生存確認)。
      3. FastAPI ``POST /api/v1/superintendent/emergency-stop`` (operator session) で engage。
         latch row が作られ (``select * from superintendent_emergency_stops where cleared_at is null``)、
         wake が ``taskmanagedai:superintendent:emergency_stop_wake`` へ publish される。
      4. MCP process の supervisor loop が wake (即時) or DB poll (<=1.5s) で engage を観測し、
         ``os.killpg(pgid, SIGKILL)`` で subprocess を kill する。subprocess が終了 (``ps`` で消滅)、
         ``managed_agents`` 行が state='stopped' になることを確認。
      5. engage 後に再度 ``superintendent_agent_start`` を呼ぶと ``state='denied' / error=
         'emergency_stop_engaged'`` (latch fail-closed deny、P1-1 解消) を確認。
      6. Redis を停止した状態で 1-4 を再実行し、**DB poll fallback のみ**でも kill されることを確認
         (Redis 単独障害で kill 不能にならない、fail-closed)。

    cleanup: throwaway stack を down。
    """
    pytest.skip("operator/integration test: requires real subprocess + 2-process 協調 (CI 不可)")
