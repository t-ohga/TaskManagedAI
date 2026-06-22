"""SP-PHASE1 B5a: worker driver atomic claim point latch interface contract (ADR-00048 §A-9)。

**SP-004-5 worker driver (ADR-00057) は未マージ** (workers は noop_task のみ、AgentRun claim point は実
コードに存在しない)。よって SP-PHASE1 は claim point に latch を「貫通」できない。代わりに **「worker driver
の atomic claim point (queued→gathering_context) は claim 確定 transaction 内で
(a) ``acquire_emergency_stop_lock(session, tenant_id)`` を**先に取得**してから
(b) ``assert_not_emergency_stopped(session, tenant_id)`` を呼ぶ」契約**を helper + contract test で固定する。

**A-9 補強 (B5 adversarial LOW-3、TOCTOU 再導入防止、ADR-00048 §A-9)**: read-only な latch check **だけ** を
claim point に置くと、spawn (``spawn_agent_managed``、A-1 §0) が P1-2 で解消したのと同じ TOCTOU race を実
driver が再導入し得る (latch 読取り→claim 確定の窓に engage が割り込む)。よって claim point は spawn と **同一
helper・同一 advisory lock key** (``superintendent-emergency-stop:<tenant>``) を取得してから latch check を
呼ぶこと。順序: advisory lock 取得 → latch check (engaged なら abort) → claim 確定 UPDATE → caller commit
(lock 解放)。本 stub driver はこの 2-step 契約 (lock → check) を模す。

本 test は:
1. 共有 helper ``assert_not_emergency_stopped`` / ``acquire_emergency_stop_lock`` が存在し callable で
   あること (driver が呼ぶ対象)。
2. helper が **fail-closed** であること: latch query が失敗しても ``EmergencyStopEngagedError`` に倒れる
   (engaged 確認不能で claim を進めない)。
3. stub driver が claim point で **advisory lock を先に取得してから** helper を呼ぶ契約: latch engaged の
   とき claim が ``EmergencyStopEngagedError`` で abort し、queued→gathering_context へ進めないこと。
4. latch off のとき stub driver が claim を進められること (regression 防止)。lock → check の順序も検証。

実 driver 駆動 (実 provider 課金前 deny) の検証は **Phase 2 (SP-004-5/ADR-00057)** で行う。本 batch は
契約予約 + stub。
"""

from __future__ import annotations

import inspect

import pytest

from backend.app.services.superintendent.emergency_stop import (
    EmergencyStopEngagedError,
    acquire_emergency_stop_lock,
    assert_not_emergency_stopped,
)


class _FakeService:
    """``EmergencyStopService`` の最小 stub (is_engaged のみ、DB 非依存)。"""

    def __init__(self, *, engaged: bool, raises: bool = False) -> None:
        self._engaged = engaged
        self._raises = raises
        self.calls = 0

    async def is_engaged(self, _tenant_id: int) -> bool:
        self.calls += 1
        if self._raises:
            raise RuntimeError("simulated latch query failure (DB error)")
        return self._engaged


class _FakeSession:
    """latch helper が受け取る session の placeholder (本 stub では query は service が担う)。"""


async def _stub_worker_claim(
    session: object, tenant_id: int, *, order: list[str] | None = None
) -> str:
    """worker driver の atomic claim point を模した stub (ADR-00048 §A-9 contract)。

    実 driver は claim 確定 SQL (queued→gathering_context の atomic UPDATE) と同一 transaction で
    (1) ``acquire_emergency_stop_lock`` を先に取得し、(2) ``assert_not_emergency_stopped`` を呼ぶ。本 stub は
    その 2-step 契約 (lock → check) を模し、check が raise すれば claim は成立しない (queued のまま)。
    ``order`` を渡すと "lock" / "check" の呼び出し順を記録する (LOW-3 contract の順序検証用)。
    """
    # A-9 補強 (LOW-3): advisory lock を **先に** 取得 (spawn と同一 helper・同一 key、TOCTOU 防止)。
    await acquire_emergency_stop_lock(session, tenant_id)  # type: ignore[arg-type]
    if order is not None:
        order.append("lock")
    # claim 確定 transaction 内 latch gate (engaged なら EmergencyStopEngagedError)。
    await assert_not_emergency_stopped(session, tenant_id)  # type: ignore[arg-type]
    if order is not None:
        order.append("check")
    return "gathering_context"


async def _noop_lock(_session: object, _tenant_id: int) -> None:
    """test 用 advisory-lock stub (real ``pg_advisory_xact_lock`` SQL を no-DB で no-op に置換)。"""
    return None


def test_assert_not_emergency_stopped_is_callable_async() -> None:
    """A-9: driver が claim point で呼ぶ共有 helper が存在し coroutine function であること。"""
    assert inspect.iscoroutinefunction(assert_not_emergency_stopped)
    sig = inspect.signature(assert_not_emergency_stopped)
    # contract: (session, tenant_id) を取る。
    assert list(sig.parameters) == ["session", "tenant_id"]


def test_acquire_emergency_stop_lock_is_callable_async() -> None:
    """A-9 補強 (LOW-3): claim point が latch check 前に取得する advisory-lock helper の契約。

    spawn (``spawn_agent_managed``、A-1 §0) と同一 helper・同一 key で serialize するため、driver は本 helper
    を claim 確定 transaction 内で **先に** 取得する。helper が存在し ``(session, tenant_id)`` を取る coroutine
    であることを契約として固定する。
    """
    assert inspect.iscoroutinefunction(acquire_emergency_stop_lock)
    sig = inspect.signature(acquire_emergency_stop_lock)
    assert list(sig.parameters) == ["session", "tenant_id"]


@pytest.mark.asyncio
async def test_helper_denies_when_latch_engaged(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeService(engaged=True)
    monkeypatch.setattr(
        "backend.app.services.superintendent.emergency_stop.EmergencyStopService",
        lambda _session: fake,
    )
    with pytest.raises(EmergencyStopEngagedError) as exc:
        await assert_not_emergency_stopped(_FakeSession(), 1)
    assert exc.value.reason_code == "emergency_stop_engaged"
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_helper_allows_when_latch_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeService(engaged=False)
    monkeypatch.setattr(
        "backend.app.services.superintendent.emergency_stop.EmergencyStopService",
        lambda _session: fake,
    )
    # raise しない。
    await assert_not_emergency_stopped(_FakeSession(), 1)
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_helper_fail_closed_on_query_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-9 fail-closed: latch query 失敗 (DB error) は deny 方向に倒す (engaged 確認不能で進めない)。"""
    fake = _FakeService(engaged=False, raises=True)
    monkeypatch.setattr(
        "backend.app.services.superintendent.emergency_stop.EmergencyStopService",
        lambda _session: fake,
    )
    with pytest.raises(EmergencyStopEngagedError):
        await assert_not_emergency_stopped(_FakeSession(), 1)


@pytest.mark.asyncio
async def test_stub_worker_claim_aborts_when_latch_engaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """contract: claim point が advisory lock → latch check を呼び、engaged 中は claim へ進めない。"""
    fake = _FakeService(engaged=True)
    monkeypatch.setattr(
        "backend.app.services.superintendent.emergency_stop.EmergencyStopService",
        lambda _session: fake,
    )
    # advisory lock は本 module 名へ束縛済のため module 名を no-op に差し替える (no-DB)。
    monkeypatch.setattr(
        "tests.superintendent.test_worker_driver_claim_contract.acquire_emergency_stop_lock",
        _noop_lock,
    )
    order: list[str] = []
    with pytest.raises(EmergencyStopEngagedError):
        await _stub_worker_claim(_FakeSession(), 1, order=order)
    # latch check が claim 確定前に呼ばれた契約。lock を先に取ってから check した (TOCTOU 防止順序)。
    assert fake.calls == 1
    assert order == ["lock"]  # check は raise したので order に積まれない (lock のみ確定)。


@pytest.mark.asyncio
async def test_stub_worker_claim_proceeds_when_latch_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeService(engaged=False)
    monkeypatch.setattr(
        "backend.app.services.superintendent.emergency_stop.EmergencyStopService",
        lambda _session: fake,
    )
    monkeypatch.setattr(
        "tests.superintendent.test_worker_driver_claim_contract.acquire_emergency_stop_lock",
        _noop_lock,
    )
    order: list[str] = []
    result = await _stub_worker_claim(_FakeSession(), 1, order=order)
    assert result == "gathering_context"
    assert fake.calls == 1
    # A-9 補強 (LOW-3): advisory lock を latch check より **先に** 取得する契約。
    assert order == ["lock", "check"]
