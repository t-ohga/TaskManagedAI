"""Cross-process agent supervisor skeleton (SP-PHASE1 B2、ADR-00048 §F、B4 で本実装)。

hybrid supervisor (user 承認 2026-06-21):
- **DB latch を source of truth (権威・fail-closed)**: 各 host process が ``managed_agents`` +
  ``superintendent_emergency_stops`` latch を poll (~1-2s) し、engage を必ず観測する fallback。
- **Redis pub/sub を best-effort 低レイテンシ wake**: engage 時 pub/sub で即 wake → SIGKILL。
  pub/sub 取りこぼし時も DB poll が回収する。

本 module は B2 では **skeleton** (loop / channel 名定数 / docstring のみ)。実 kill / poll / wake は
B4 で実装する。新規活動 deny は B5 の choke point 同期 latch check が担い (poll 待ちでない)、supervisor
は **既起動 subprocess の kill のみ** を担当する。
"""

from __future__ import annotations

import logging
import os
import signal
from collections.abc import Iterable

from backend.app.services.superintendent.host_identity import get_host_boot_id
from backend.app.services.superintendent.managed_agent_registry import (
    ManagedAgentRegistry,
    ManagedAgentView,
)

logger = logging.getLogger(__name__)

#: emergency-stop engage を host supervisor へ即時 wake する Redis pub/sub channel (B4 で publish/subscribe)。
SUPERVISOR_WAKE_CHANNEL: str = "taskmanagedai:superintendent:emergency_stop_wake"

#: DB latch poll の fallback interval (秒)。pub/sub 取りこぼし時もこの周期で engage を観測する。
SUPERVISOR_POLL_INTERVAL_SECONDS: float = 1.5


def _killable(view: ManagedAgentView, *, host_id: str, host_boot_id: str | None) -> bool:
    """この host が当該 row を kill してよいか (A-2: host scope + pid/pgid 再利用防御)。

    - 別 host の pgid は絶対 signal しない (host_id scope)。
    - boot_id 不一致 (host reboot 後の pgid 再利用) は signal しない (誤 kill 防止)。
      row の boot_id が None (旧 row) の場合は best-effort で許可する。

    **honest limit (LOW-6)**: row.boot_id が None (boot_id 取得不能 host、または旧 row) かつ
    host_boot_id も None の場合、reboot 後に死亡 process の pgid を無関係 process が再利用していると
    **誤 kill する窓**が残る (boot_id 照合が無効化されるため)。B4 で ``started_at`` 照合 (kill 前に
    process 起動時刻と DB row の started_at を突合) を追加してこの窓を縮める。ADR-00048 §A-2 / §残リスク
    にも明記。本判定は host scope + (取得できれば) boot_id 照合の二重防御で、boot_id 取得可能環境
    (Linux /proc/.../boot_id) では誤 kill しない。
    """
    if view.host_id != host_id:
        return False
    if view.process_group_id is None:
        return False
    if view.boot_id is not None and host_boot_id is not None and view.boot_id != host_boot_id:
        return False
    return True


def _killpg(view: ManagedAgentView) -> bool:
    """managed_agent row の pgid を SIGKILL する (in-process handle 不要、A-2)。

    supervisor restart で in-process Process handle を失っても DB の process_group_id から killpg で
    kill 到達できる。signal 不能 (既に死亡 / 権限) は no-op として扱う。
    """
    if view.process_group_id is None:
        return False
    try:
        os.killpg(view.process_group_id, signal.SIGKILL)
        return True
    except (ProcessLookupError, OSError):
        return False


async def kill_managed_agents_on_host(
    *,
    registry: ManagedAgentRegistry,
    tenant_id: int,
    host_id: str,
) -> list[ManagedAgentView]:
    """B4 placeholder: 当該 host × tenant の active row を列挙し killpg する。

    B2 skeleton では「列挙 + killable 判定 + killpg」の構造だけ提供する。実際の engage→wake→kill の
    orchestration (latch generation 確認 / managed_agents terminalize / audit) は B4 で実装する。
    """
    boot_id = get_host_boot_id()
    targets = await registry.list_active_on_host(host_id=host_id, tenant_id=tenant_id)
    killed: list[ManagedAgentView] = []
    for view in targets:
        if _killable(view, host_id=host_id, host_boot_id=boot_id):
            if _killpg(view):
                killed.append(view)
    return killed


async def supervisor_poll_once(
    *,
    registry: ManagedAgentRegistry,
    host_id: str,
    engaged_tenant_id: int,
) -> Iterable[ManagedAgentView]:
    """B4 placeholder: DB latch poll を 1 周回する (skeleton、tenant-scoped)。

    LOW-3: host-wide (cross-tenant) 列挙を避けるため **tenant-scope 設計**にする。B4 の poll loop は:
      1. ``superintendent_emergency_stops`` latch を読み、**engaged な tenant を解決** (B3)。
      2. その engaged tenant に**絞って** active row を列挙し ``kill_managed_agents_on_host`` で kill。

    本 skeleton は (1) を呼出側 (B4) が解決した ``engaged_tenant_id`` を受け取り、(2) の列挙を
    必ず tenant scope (``list_active_on_host(host_id, tenant_id=engaged_tenant_id)``) で行う。
    tenant 無し host-wide 列挙はしない (engage された tenant の subprocess のみ kill 対象)。B2 では
    列挙のみ (kill しない)。
    """
    logger.debug(
        "supervisor_poll_skeleton",
        extra={"host_id": host_id, "engaged_tenant_id": engaged_tenant_id},
    )
    return await registry.list_active_on_host(
        host_id=host_id, tenant_id=engaged_tenant_id
    )


__all__ = [
    "SUPERVISOR_POLL_INTERVAL_SECONDS",
    "SUPERVISOR_WAKE_CHANNEL",
    "kill_managed_agents_on_host",
    "supervisor_poll_once",
]
