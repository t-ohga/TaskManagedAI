"""Cross-process agent supervisor (SP-PHASE1 B4、ADR-00048 §F / §Amendment A-1/A-2)。

hybrid supervisor (user 承認 2026-06-21):
- **DB latch を source of truth (権威・fail-closed)**: agent を spawn する host process が
  ``superintendent_emergency_stops`` latch を ``SUPERVISOR_POLL_INTERVAL_SECONDS`` 毎に poll し、
  engage を必ず観測する fallback。Redis 単独障害でも kill 不能にならない (fail-closed)。
- **Redis pub/sub ``SUPERVISOR_WAKE_CHANNEL`` を best-effort 低レイテンシ wake**: engage 時に
  publish し、subscribe 中の各 host を即 wake → SIGKILL。pub/sub 取りこぼし時も DB poll が回収する。

責務 (A-3): supervisor は **既起動 subprocess の kill のみ** を担当する (DB-backed ``managed_agents`` の
``host_id`` + ``process_group_id`` を見て ``os.killpg(pgid, SIGKILL)``)。新規活動 deny は B5 の choke point
同期 latch check が担う (poll 待ちでない)。kill 実行は当該 subprocess を spawn した **同一 host の
supervisor のみ** (A-2、別 host の pgid は絶対 signal しない)。

**PID namespace invariant (B4 adversarial HIGH-1、最重要)**: supervisor は **agent を spawn した
同一 PID namespace の process でのみ動かす**。``killpg(pgid)`` の唯一の gate は ``host_id`` 等価であり、
``boot_id`` / ``started_at`` は **PID namespace を識別しない** (container 間で boot_id 共有、started_at は
namespace-blind)。よって:
- managed agent を spawn するのは **MCP server host process のみ** → supervisor も MCP server lifespan
  でのみ配線する。
- worker は **Docker container = 別 PID namespace** で動き agent を spawn しないため、**supervisor を
  worker に配線しない** (配線すると別 namespace で MCP-spawned pgid に killpg → ProcessLookupError →
  「消滅」誤判定 → mark_terminal(stopped) で実 process は host で生存 = **fail-open**)。
- ``TASKMANAGEDAI_SUPERVISOR_HOST_ID`` を **異なる PID namespace (container) 間で共有してはならない**
  (host_id を共有すると worker supervisor が MCP-spawned row を選び別 namespace で誤 kill する)。
"""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime
from enum import Enum
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.db.models.superintendent_emergency_stop import SuperintendentEmergencyStop
from backend.app.services.superintendent.host_identity import get_host_boot_id
from backend.app.services.superintendent.managed_agent_registry import (
    ManagedAgentRegistry,
    ManagedAgentView,
)

logger = logging.getLogger(__name__)

#: emergency-stop engage を host supervisor へ即時 wake する Redis pub/sub channel (B4 publish/subscribe)。
SUPERVISOR_WAKE_CHANNEL: str = "taskmanagedai:superintendent:emergency_stop_wake"

#: DB latch poll の fallback interval (秒)。pub/sub 取りこぼし時もこの周期で engage を観測する。
SUPERVISOR_POLL_INTERVAL_SECONDS: float = 1.5

class _WakePubSub(Protocol):
    """Redis pubsub の wake subscribe 契約 (test で in-memory 実装に差し替え可能)。"""

    async def subscribe(self, *channels: str) -> object: ...

    async def get_message(
        self, ignore_subscribe_messages: bool = True, **kwargs: object
    ) -> object | None: ...


class _WakeRedis(Protocol):
    """``pubsub()`` を持つ Redis client 契約 (best-effort wake subscribe 用)。"""

    def pubsub(self) -> _WakePubSub: ...


#: pid/pgid 再利用防御 (A-2 §B4): kill 実行 host で取得した process 起動時刻と DB row の started_at が
#: 本許容差 (秒) を超えて乖離していたら signal しない。pid が再利用され別 process になっている疑いが
#: あるため (boot_id 照合が無効化される旧 row / boot_id 取得不能 host の窓を縮める)。
_STARTED_AT_TOLERANCE_SECONDS: float = 5.0


def _killable(view: ManagedAgentView, *, host_id: str, host_boot_id: str | None) -> bool:
    """この host が当該 row を kill してよいか (A-2: host scope + pid/pgid 再利用防御)。

    - 別 host の pgid は絶対 signal しない (host_id scope)。
    - boot_id 不一致 (host reboot 後の pgid 再利用) は signal しない (誤 kill 防止)。
      row の boot_id が None (旧 row) の場合は best-effort で許可する。

    **honest limit (LOW-6)**: row.boot_id が None (boot_id 取得不能 host、または旧 row) かつ
    host_boot_id も None の場合、reboot 後に死亡 process の pgid を無関係 process が再利用していると
    **誤 kill する窓**が残る (boot_id 照合が無効化されるため)。B4 で kill 時に ``started_at`` 照合
    (process 起動時刻と DB row の started_at を突合、``_started_at_consistent``) を追加してこの窓を
    縮める。ADR-00048 §A-2 / §残リスク にも明記。本判定は host scope + (取得できれば) boot_id 照合 +
    started_at 照合の三重防御で、boot_id 取得可能環境 (Linux /proc/.../boot_id) では誤 kill しない。
    """
    if view.host_id != host_id:
        return False
    if view.process_group_id is None:
        return False
    if view.boot_id is not None and host_boot_id is not None and view.boot_id != host_boot_id:
        return False
    return True


def _proc_started_at(pid: int) -> datetime | None:
    """pid の process 起動時刻を best-effort で返す (A-2 started_at 照合用、取得不能なら None)。

    psutil が無い環境でも壊れないよう optional import。boot_id 照合が無効化される窓 (旧 row /
    boot_id 取得不能 host) の補助防御で、started_at 取得不能時は本照合を skip する (best-effort、
    host scope + boot_id が主防御)。

    **honest limit (M1 adversarial review adopt)**: ``psutil`` は本 batch では **hard runtime 依存に
    していない** (lazy optional import)。psutil 不在環境では started_at 照合は完全に inert になり、
    pid 再利用 misfire 防御は host scope + (取得可能なら) boot_id のみ = B4 以前と同等の窓が残る。
    started_at 防御を有効化したい deploy では psutil を runtime に追加すること。ADR-00048 §A-2
    honest limit / §残リスク と整合 (started_at は窓を「縮める」補助であり主防御ではない)。
    """
    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        logger.debug(
            "supervisor_started_at_check_inert (psutil absent; host+boot_id are primary defense)"
        )
        return None
    try:
        from datetime import UTC

        return datetime.fromtimestamp(psutil.Process(pid).create_time(), tz=UTC)
    except Exception:  # noqa: BLE001 — psutil の各種例外 (NoSuchProcess/AccessDenied 等) は照合 skip
        return None


def _started_at_consistent(view: ManagedAgentView) -> bool:
    """row の started_at と現 host 上の process 起動時刻が整合するか (A-2 §B4 pid 再利用防御)。

    - row.started_at または row.pid が無ければ照合不能 → best-effort True (boot_id/host scope が主防御)。
    - 現 host で pid の起動時刻が取得できなければ照合不能 → True (psutil 不在 / 権限不足)。
    - 取得できた場合、許容差 (``_STARTED_AT_TOLERANCE_SECONDS``) を超える乖離は **別 process** (pid 再利用)
      と判定し False (signal しない)。
    """
    if view.started_at is None or view.pid is None:
        return True
    actual = _proc_started_at(view.pid)
    if actual is None:
        return True
    delta = abs((actual - view.started_at).total_seconds())
    return delta <= _STARTED_AT_TOLERANCE_SECONDS


class _KillOutcome(Enum):
    """killpg の結果分類 (H2: terminalize 判断に EPERM = alive を区別する)。"""

    KILLED = "killed"  #: signal 到達 (process group へ SIGKILL 送信成功)。
    ALREADY_GONE = "already_gone"  #: ProcessLookupError = process は既に消滅 (terminalize 可)。
    STILL_ALIVE = "still_alive"  #: EPERM 等 = process は **生存** だが signal 不能 (terminalize 不可、retry)。


def _killpg(view: ManagedAgentView) -> _KillOutcome:
    """managed_agent row の pgid を SIGKILL する (in-process handle 不要、A-2)。

    supervisor restart で in-process Process handle を失っても DB の process_group_id から killpg で
    kill 到達できる。**H2 (adversarial review adopt)**: signal 不能でも一律「死亡」扱いにしない:
    - ``ProcessLookupError`` (ESRCH) → process は既に消滅 (``ALREADY_GONE``、terminalize 可)。
    - ``PermissionError`` / ``EPERM`` → process は **生存** だが権限不足で signal できない
      (``STILL_ALIVE``)。これを「死亡」扱いで terminalize すると、生存中の un-killable agent を
      ``stopped`` と記録して以後 retry されず **fail-open** になる。terminalize せず loud WARN + 次 poll
      で retry する。
    - その他 OSError も保守的に ``STILL_ALIVE`` 扱い (terminalize しない、retry)。

    **HIGH-2 (adversarial review adopt) — pgid<=0 guard**: ``os.killpg(0, SIGKILL)`` は **呼び出し元
    (supervisor) 自身の process group 全体に SIGKILL** を送り self-kill + 巻き添えになる。負 pgid も
    POSIX kill の特殊指定 (process group / 全 process)。corrupted/zero/負 pgid は **killpg を呼ばず
    skip** (``ALREADY_GONE`` 扱い + loud error)。DB CHECK (migration 0054) + ORM CheckConstraint と
    合わせ 4-layer で 0/負 pgid を排除する。
    """
    pgid = view.process_group_id
    if pgid is None:
        return _KillOutcome.ALREADY_GONE
    if pgid <= 0:
        # HIGH-2: 0/負 pgid を killpg に渡すと self-kill (pgid=0) / 特殊 signal 範囲になる。送らない。
        logger.error(
            "supervisor_killpg_refused_nonpositive_pgid (would self-kill; row NOT terminalized)",
            extra={"managed_agent_id": str(view.id)},
        )
        return _KillOutcome.STILL_ALIVE
    try:
        os.killpg(pgid, signal.SIGKILL)
        return _KillOutcome.KILLED
    except ProcessLookupError:
        return _KillOutcome.ALREADY_GONE
    except PermissionError:
        return _KillOutcome.STILL_ALIVE
    except OSError as exc:
        # EPERM は PermissionError で捕捉済。残り OSError は保守的に「生存・signal 不能」扱い
        # (terminalize しない = fail-open を避ける)。ESRCH を OSError 経路で受けた場合のみ gone。
        if exc.errno == errno.ESRCH:
            return _KillOutcome.ALREADY_GONE
        return _KillOutcome.STILL_ALIVE


async def kill_managed_agents_on_host(
    *,
    registry: ManagedAgentRegistry,
    tenant_id: int,
    host_id: str,
) -> list[ManagedAgentView]:
    """当該 host × tenant の active row (state∈{spawning,running}) を列挙し killpg + terminalize する。

    手順 (A-2):
      1. host × tenant に絞って active 行を列挙 (別 host / 別 tenant は絶対列挙しない)。
      2. 各行に ``_killable`` (host_id scope + boot_id 照合) + ``_started_at_consistent`` (pid 再利用
         防御) を適用。
      3. pgid が確定している行 (running) は ``os.killpg(pgid, SIGKILL)`` で kill。pid 未確定の spawning
         行 (pgid IS NULL) は kill skip し、DB 行も terminalize しない (= 次 poll で再評価、A-1 ordering
         で running 化されるまで列挙され続け、running 化後に kill される)。
      4. **kill 到達 (KILLED) / 既消滅 (ALREADY_GONE) のみ** ``mark_terminal(stopped)`` で terminal 化。
         **EPERM 等で生存 (STILL_ALIVE) は terminalize せず loud WARN + 次 poll で retry** (H2: 生存中の
         un-killable agent を stopped と誤記録して fail-open するのを防ぐ)。

    **H1 (adversarial review adopt)**: 同一 host で MCP / worker の 2 supervisor が並走するため、active 行を
    ``FOR UPDATE SKIP LOCKED`` で列挙し、片方が掴んだ行をもう片方が触らない (reused-pgid の二重 signal +
    audit double-count を防ぐ)。row lock は kill_managed_agents_on_host の transaction (caller commit) で保持。

    **honest defer (M3、adversarial review)**: stale ``spawning`` 行 (A-1 ordering 外 / crash で残った
    pid NULL 行) の reconciliation (spawn timeout 超過で ``failed`` 化) は **B4 では未実装**、B6 で実装。
    本関数は ``spawning`` を skip するのみ。A-1 ordering 下の live spawn は advisory lock 内で ``running``
    へ進むため kill-miss にはならない。ADR-00048 §残リスク参照。

    raw pid / pgid は本関数の戻り値や log に raw で出さない (view の id / host のみ)。
    """
    boot_id = get_host_boot_id()
    targets = await registry.list_active_on_host(
        host_id=host_id, tenant_id=tenant_id, for_update_skip_locked=True
    )
    killed: list[ManagedAgentView] = []
    for view in targets:
        # spawning (pgid 未確定) は kill 対象外 (terminalize もしない)。次 poll で running 化後に kill。
        # A-1 ordering 下では spawn は advisory lock 内で running まで進むため、kill 漏れにはならない。
        if view.process_group_id is None:
            logger.debug(
                "supervisor_skip_pending_spawn",
                extra={"managed_agent_id": str(view.id), "host_id": host_id},
            )
            continue
        if not _killable(view, host_id=host_id, host_boot_id=boot_id):
            continue
        if not _started_at_consistent(view):
            logger.warning(
                "supervisor_skip_started_at_mismatch",
                extra={"managed_agent_id": str(view.id), "host_id": host_id},
            )
            continue
        outcome = _killpg(view)
        if outcome is _KillOutcome.STILL_ALIVE:
            # H2: EPERM 等で生存中だが signal 不能。terminalize すると fail-open。retry させる。
            logger.error(
                "supervisor_kill_unkillable_alive (process survives, NOT terminalized, will retry)",
                extra={
                    "managed_agent_id": str(view.id),
                    "host_id": host_id,
                    "tenant_id": tenant_id,
                },
            )
            continue
        # KILLED / ALREADY_GONE のみ terminal 化 (再 kill 試行を避け registry を整合させる)。
        await registry.mark_terminal(
            tenant_id=tenant_id,
            managed_agent_id=view.id,
            state="stopped",
        )
        killed.append(view)
        logger.info(
            "supervisor_killed_managed_agent",
            extra={
                "managed_agent_id": str(view.id),
                "host_id": host_id,
                "tenant_id": tenant_id,
                "kill_outcome": outcome.value,
            },
        )
    return killed


async def _engaged_tenant_ids(session: AsyncSession) -> list[int]:
    """active emergency-stop latch を持つ tenant id を列挙する (cleared_at IS NULL = engaged)。

    DB latch が権威 (fail-closed): pub/sub wake 取りこぼし時も本 poll が engaged tenant を必ず観測する。
    host-wide cross-tenant kill を避けるため、engaged tenant に絞って kill する (LOW-3 tenant scope)。
    """
    rows = await session.scalars(
        sa.select(SuperintendentEmergencyStop.tenant_id).where(
            SuperintendentEmergencyStop.cleared_at.is_(None)
        )
    )
    # 同 tenant に複数 active latch が並ぶことは partial unique で無いが、dedup で防御的に。
    return sorted(set(rows.all()))


async def supervisor_poll_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    host_id: str,
) -> list[ManagedAgentView]:
    """DB latch poll を 1 周回し、engaged tenant の自 host subprocess を kill する (権威 fallback)。

    1. ``superintendent_emergency_stops`` latch を読み engaged tenant を解決 (DB 権威、B3)。
    2. その engaged tenant に**絞って** active 行を host scope で列挙し ``kill_managed_agents_on_host``。

    tenant 無し host-wide 列挙はしない (engage された tenant の subprocess のみ kill 対象、LOW-3)。
    各 tenant の kill は **独立 transaction** で commit する (1 tenant の失敗が他 tenant の kill を巻き
    込まない)。

    **MEDIUM-3 (adversarial review adopt)**: kill session の ``mark_terminal`` commit を host-freeze DML
    mutation gate から exempt する (``mark_emergency_stop_bypass``、ADR-00048 §A-3 と同思想)。supervision
    (cross-process kill) は host-freeze と独立した安全機構であり、freeze 中も terminalize を永続化しないと
    「kill したのに記録が残らず以後 retry されない」fail-open になる。bypass allowlist に
    ``ManagedAgentRecord`` を追加済 (無関係 model 混入は fail-closed reject)。
    """
    from backend.app.db.active_registry_mutation_gate import mark_emergency_stop_bypass

    killed: list[ManagedAgentView] = []
    async with session_factory() as session:
        engaged = await _engaged_tenant_ids(session)
    for tenant_id in engaged:
        async with session_factory() as session:
            # MEDIUM-3: supervision write (mark_terminal) を freeze gate から exempt。
            mark_emergency_stop_bypass(session)
            registry = ManagedAgentRegistry(session)
            tenant_killed = await kill_managed_agents_on_host(
                registry=registry, tenant_id=tenant_id, host_id=host_id
            )
            await session.commit()
            killed.extend(tenant_killed)
    return killed


class EmergencyStopSupervisor:
    """hybrid (Redis wake + DB poll) supervisor loop を 1 host process に駆動する。

    起動配線 (B4 §5): agent を spawn する host process (MCP server / worker) の startup で本 loop を
    background task として起動する。FastAPI process は engage で latch + wake publish するが kill は
    本 supervisor (MCP/worker) が担う (cross-process、A-2「同一 host の supervisor のみ kill」)。

    - ``run()``: cancellable loop。Redis pub/sub subscribe で即時 wake、取りこぼし / Redis 障害時は
      ``poll_interval`` 毎の DB poll で必ず engage を観測する (fail-closed)。例外で死なない
      (poll fallback を継続)。
    - Redis 接続は best-effort (低レイテンシ最適化)。Redis 単独障害で kill 不能にならない。
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        host_id: str,
        redis_factory: Callable[[], Awaitable[_WakeRedis] | _WakeRedis] | None = None,
        wake_channel: str = SUPERVISOR_WAKE_CHANNEL,
        poll_interval: float = SUPERVISOR_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._host_id = host_id
        self._redis_factory = redis_factory
        self._wake_channel = wake_channel
        self._poll_interval = poll_interval
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def _poll(self) -> None:
        """1 周回の DB poll + kill。例外は握り潰して loop を継続する (fail-closed fallback)。"""
        try:
            killed = await supervisor_poll_once(
                session_factory=self._session_factory, host_id=self._host_id
            )
            if killed:
                logger.info(
                    "supervisor_poll_killed",
                    extra={"host_id": self._host_id, "killed_count": len(killed)},
                )
        except Exception:  # noqa: BLE001 — poll は安全機能。例外で loop を殺さず次周回へ。
            logger.warning(
                "supervisor_poll_error", extra={"host_id": self._host_id}, exc_info=True
            )

    async def run(self) -> None:
        """hybrid loop。Redis wake が来れば即 poll、来なくても poll_interval 毎に poll。

        Redis pubsub 取得 / subscribe に失敗しても DB poll 専用 loop に degrade する (fail-closed)。
        """
        logger.info(
            "supervisor_loop_started",
            extra={"host_id": self._host_id, "wake_channel": self._wake_channel},
        )
        pubsub = await self._try_subscribe()
        try:
            # 起動直後に 1 回 poll (loop 起動前に既に engaged だった latch を回収する)。
            await self._poll()
            while not self._stop.is_set():
                woke = await self._wait_for_wake_or_timeout(pubsub)
                if self._stop.is_set():
                    break
                if woke:
                    logger.info(
                        "supervisor_wake_received", extra={"host_id": self._host_id}
                    )
                await self._poll()
        finally:
            await self._close_pubsub(pubsub)
            logger.info("supervisor_loop_stopped", extra={"host_id": self._host_id})

    async def _try_subscribe(self) -> _WakePubSub | None:
        """Redis pubsub を subscribe する (best-effort、失敗時 None で DB poll 専用へ degrade)。"""
        if self._redis_factory is None:
            return None
        try:
            produced = self._redis_factory()
            redis: _WakeRedis = (
                await produced if isinstance(produced, Awaitable) else produced
            )
            pubsub = redis.pubsub()
            await pubsub.subscribe(self._wake_channel)
            return pubsub
        except Exception:  # noqa: BLE001 — Redis 障害でも DB poll fallback で動く (fail-closed)。
            logger.warning(
                "supervisor_redis_subscribe_failed (degraded to DB poll only)",
                extra={"host_id": self._host_id},
                exc_info=True,
            )
            return None

    async def _wait_for_wake_or_timeout(self, pubsub: _WakePubSub | None) -> bool:
        """wake message を ``poll_interval`` まで待つ。message 受信で True、timeout で False。

        pubsub が無い (degraded) 場合は単純な timeout sleep (DB poll 専用)。Redis 障害で get_message が
        例外を投げても timeout 扱いにして DB poll を継続する (fail-closed)。
        """
        if pubsub is None:
            with suppress(TimeoutError, asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
            return False
        try:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=self._poll_interval
            )
        except Exception:  # noqa: BLE001 — Redis 障害は timeout 扱い → DB poll 継続 (fail-closed)。
            logger.warning(
                "supervisor_redis_get_message_failed (falling back to DB poll)",
                extra={"host_id": self._host_id},
                exc_info=True,
            )
            return False
        return message is not None

    @staticmethod
    async def _close_pubsub(pubsub: _WakePubSub | None) -> None:
        if pubsub is None:
            return
        close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
        if close is None:
            return
        with suppress(Exception):
            result = close()
            if asyncio.iscoroutine(result):
                await result


def build_default_supervisor(
    redis_factory: Callable[[], Awaitable[_WakeRedis] | _WakeRedis] | None = None,
) -> EmergencyStopSupervisor:
    """既定 settings から host supervisor を組み立てる (MCP server / worker startup 配線用)。

    - session factory は ``mcp.context`` の共有 engine を再利用する (DB latch poll + kill 用)。
    - host_id は ``agent_spawner.default_host_id`` (spawn 側と同一値 = A-2 同一 host scope を満たす)。
    - redis_factory 未指定なら settings.redis_url から best-effort で Redis client を作る (wake subscribe、
      接続失敗時は DB poll 専用に degrade)。
    """
    from backend.app.config import get_settings
    from backend.app.mcp.context import get_session_factory
    from backend.app.services.superintendent.agent_spawner import default_host_id

    settings = get_settings()

    if redis_factory is None:
        redis_url = settings.redis_url

        def _default_redis_factory() -> _WakeRedis:
            from typing import cast

            from redis.asyncio import Redis

            return cast(_WakeRedis, Redis.from_url(redis_url, decode_responses=True))

        redis_factory = _default_redis_factory

    return EmergencyStopSupervisor(
        session_factory=get_session_factory(),
        host_id=default_host_id(),
        redis_factory=redis_factory,
    )


def start_supervisor_background_task(
    supervisor: EmergencyStopSupervisor,
) -> asyncio.Task[None]:
    """supervisor.run() を background task として起動する (caller が shutdown 時に cancel する)。"""
    return asyncio.create_task(supervisor.run())


__all__ = [
    "EmergencyStopSupervisor",
    "SUPERVISOR_POLL_INTERVAL_SECONDS",
    "SUPERVISOR_WAKE_CHANNEL",
    "build_default_supervisor",
    "kill_managed_agents_on_host",
    "start_supervisor_background_task",
    "supervisor_poll_once",
]
