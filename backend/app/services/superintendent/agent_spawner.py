"""Agent process spawner: starts AI agent subprocesses.

Each agent runs as a separate process (claude / codex / custom)
with its own MCP client config pointing to TaskManagedAI.

Security:
- Subprocess env is scrubbed (no raw secrets)
- Agent process runs in project-scoped workdir
- Kill switch terminates process group
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import socket
import stat as stat_mod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from backend.app.services.superintendent.host_identity import get_host_boot_id

if TYPE_CHECKING:
    from uuid import UUID as _UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.app.services.superintendent.managed_agent_registry import (
        ManagedAgentRegistry,
    )

logger = logging.getLogger(__name__)

AgentProvider = Literal["claude", "codex", "custom"]

SPAWN_TIMEOUT_SECONDS = 30
STOP_GRACE_SECONDS = 10


def default_host_id() -> str:
    """現 host の supervision host_id (kill 到達性 A-2)。env override 可、default は hostname。"""
    return os.environ.get("TASKMANAGEDAI_SUPERVISOR_HOST_ID") or socket.gethostname()


async def _assert_not_emergency_stopped(tenant_id: int) -> None:
    """emergency-stop latch check の **no-op stub** (SP-PHASE1 B2、ADR-00048 §A-1)。

    B3 (emergency-stop latch + service) が本体を実装する: advisory lock 下で
    ``superintendent_emergency_stops`` latch を fail-closed check し、engaged なら
    ``EmergencyStopEngagedError`` を raise して spawn を abort する。

    B2 時点では latch table が無いため常に allow (no-op)。本 stub は spawn 冒頭の latch-check hook を
    呼ぶ場所を確立し、A-1 の advisory lock + ordering 構造を先に用意する目的で存在する。
    """
    _ = tenant_id  # B3 で latch query に使う。
    return None


class ManagedAgentTerminalizedDuringSpawn(RuntimeError):
    """spawn 中に spawning 行が concurrent terminalize された (MEDIUM-2、A-1)。

    ``mark_running`` が False (spawning 行が既に terminal 化済み) を返した場合に raise する。
    live process は呼出側 compensating path で killpg され、``_active_agents`` には登録されない
    (DB 行 terminal + live process 生存 の unkillable orphan を作らない)。
    """

    def __init__(self, managed_agent_id: UUID) -> None:
        super().__init__(
            f"managed_agent {managed_agent_id} was terminalized during spawn "
            "(mark_running returned no row)"
        )
        self.managed_agent_id = managed_agent_id


_ENV_ALLOW_KEYS = frozenset({
    "PATH", "HOME", "LANG", "LC_ALL", "SHELL", "TERM", "TZ",
    "USER", "LOGNAME", "TMPDIR", "XDG_RUNTIME_DIR",
})


@dataclass
class SpawnedAgent:
    agent_id: UUID
    provider: AgentProvider
    process: asyncio.subprocess.Process | None = None
    pid: int | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    exit_code: int | None = None


_active_agents: dict[UUID, SpawnedAgent] = {}


#: 子へ渡す最小 trusted PATH の候補 (system 標準のみ、user-writable / tmp / cwd を除外)。
_TRUSTED_PATH_DIRS = (
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
    "/opt/homebrew/bin",
)


def _untrusted_transient_prefixes() -> tuple[str, ...]:
    """executable 解決を拒否する user-writable / transient prefix (Codex R10 F-15)。"""
    prefixes = ["/tmp", "/private/tmp", "/var/tmp", "/dev/shm"]  # noqa: S108 — 拒否対象の prefix
    tmpdir = os.environ.get("TMPDIR")
    if tmpdir:
        prefixes.append(tmpdir)
    return tuple(os.path.realpath(p) for p in prefixes)


def _is_under(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:  # 別ドライブ等 → 配下でない。
        return False


def _path_mode(path: str) -> int | None:
    """path の st_mode を返す (不在なら None)。test では本関数を mock する。"""
    try:
        return os.stat(path).st_mode
    except OSError:
        return None


def _assert_not_writable_by_others(path: str) -> None:
    """path が group / world writable なら拒否する (Codex R12 F-17)。

    他ユーザが書き換え可能な executable / dir は command hijack vector。user-owned (700/755) の
    ``~/.local/bin`` 等の正規 install 先は通す (固定 allowlist 化は SP-035 architecture の範囲)。
    shutil.which は実在を保証するため通常 stat は成功する (不在なら skip)。
    """
    mode = _path_mode(path)
    if mode is None:
        return
    if mode & (stat_mod.S_IWGRP | stat_mod.S_IWOTH):
        raise ValueError(f"refusing group/world-writable agent executable path: {path}")


def _resolve_executable(name: str, project_dir: str) -> str:
    """provider executable を **trusted** な絶対 path へ解決する (SP-034、Codex R5 F-7 / R10 F-15)。

    PATH 解決の bare executable は poisoned PATH / project-local / tmp binary で command hijack され得る
    (AI agent は HOME/config 経由で user 資格情報にアクセスし得るため影響大)。次を満たさなければ拒否:
    - PATH 上に存在し絶対 path に解決できる。
    - 解決先が ``project_dir`` 配下でない (project-local binary hijack 拒否)。
    - 解決先が tmp / user-writable transient prefix 配下でない (ambient PATH poisoning 拒否、R10 F-15)。

    **honest 限界**: ambient PATH に user-writable な非標準 dir が混じる構成での完全な trust 判定は
    環境依存 (claude/codex の install 先が ~/.local/bin 等のため固定 allowlist 化できない)。設定済み
    絶対パス allowlist 化は SP-035 agent-supervision architecture (task #16) の範囲。
    """
    resolved = shutil.which(name)
    if resolved is None:
        raise FileNotFoundError(f"agent executable not found on PATH: {name}")
    resolved = os.path.realpath(resolved)
    if not os.path.isabs(resolved):
        raise ValueError(f"agent executable did not resolve to an absolute path: {name}")
    project_real = os.path.realpath(project_dir)
    if _is_under(resolved, project_real):
        raise ValueError(f"refusing project-local agent executable: {name} ({resolved})")
    # Codex R10 F-15: ambient PATH poisoning (/tmp/bin/claude 等) を拒否する。
    for prefix in _untrusted_transient_prefixes():
        if _is_under(resolved, prefix):
            raise ValueError(f"refusing agent executable under transient dir: {name} ({resolved})")
    # Codex R12 F-17: 他ユーザ writable な executable / dir は command hijack vector として拒否。
    _assert_not_writable_by_others(resolved)
    _assert_not_writable_by_others(os.path.dirname(resolved))
    return resolved


def _build_agent_command(provider: AgentProvider, project_dir: str) -> list[str]:
    if provider == "claude":
        return [
            _resolve_executable("claude", project_dir),
            "--mcp-config",
            ".mcp.json",
            "--print",
            "--dangerously-skip-permissions",
        ]
    if provider == "codex":
        return [
            _resolve_executable("codex", project_dir),
            "exec",
            "-C",
            project_dir,
            "--sandbox",
            "read-only",
        ]
    return [_resolve_executable("echo", project_dir), "custom-agent-stub"]


def _build_safe_env(project_dir: str, executable: str | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOW_KEYS and k != "PATH"}
    # Codex R10 F-15: 子へ ambient PATH を継承させず最小 trusted PATH に再構成する
    # (poisoned PATH を agent へ持ち越さない defense-in-depth)。解決済み executable の dir は
    # sibling helper のため先頭に含める。
    path_dirs: list[str] = []
    if executable:
        path_dirs.append(os.path.dirname(os.path.realpath(executable)))
    path_dirs.extend(d for d in _TRUSTED_PATH_DIRS if os.path.isdir(d))
    env["PATH"] = ":".join(dict.fromkeys(d for d in path_dirs if d))
    env["TASKMANAGEDAI_AGENT_MODE"] = "true"
    env["TASKMANAGEDAI_PROJECT_DIR"] = project_dir
    return env


async def _start_subprocess(
    provider: AgentProvider, project_dir: str
) -> asyncio.subprocess.Process:
    cmd = _build_agent_command(provider, project_dir)
    env = _build_safe_env(project_dir, executable=cmd[0])

    # Codex R6 F-9: 未使用 pipe で child を hang させない。現状 spawner は stdin へ prompt を書かず
    # stdout/stderr を drain しないため、PIPE のままだと child が stdin 待ち / 出力 pipe 満杯で block
    # し得る。stub レベルでは DEVNULL が正しい (prompt 受け渡し / 出力捕捉は SP-035 supervisor
    # architecture の範囲)。
    return await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
        cwd=project_dir,
        start_new_session=True,
    )


async def spawn_agent(
    agent_id: UUID,
    provider: AgentProvider,
    project_dir: str,
) -> SpawnedAgent:
    """legacy process-only spawn (cross-process registry を持たない、B4 で managed 経路へ移行)。

    DB-backed registry / latch ordering は ``spawn_agent_managed`` (A-1) を使う。本関数は MCP server
    の現行 caller が DB session を持たないため互換用に残す (cross-process kill の正本にはならない)。
    """
    proc = await _start_subprocess(provider, project_dir)
    agent = SpawnedAgent(
        agent_id=agent_id,
        provider=provider,
        process=proc,
        pid=proc.pid,
        started_at=datetime.now(UTC),
    )
    _active_agents[agent_id] = agent
    return agent


async def spawn_agent_managed(
    *,
    agent_id: UUID,
    provider: AgentProvider,
    project_dir: str,
    tenant_id: int,
    project_id: _UUID,
    registry: ManagedAgentRegistry,
    session: AsyncSession,
    host_id: str | None = None,
    agent_run_id: _UUID | None = None,
    supervisor_id: str | None = None,
) -> SpawnedAgent:
    """A-1 ordering で agent subprocess を spawn し DB-backed registry に登録する。

    順序 (ADR-00048 §Amendment A-1、unkillable orphan 防止):
      1. latch check (``_assert_not_emergency_stopped``、B3 で本体実装)。engaged なら abort。
      2. ``register_spawning`` (state=spawning) で DB 行を pre-register (process 起動前)。
      3. process 起動 (``start_new_session=True`` で process group leader 化)。
      4. ``mark_running`` で pid / pgid / boot_id を確定し state=running へ遷移。
      5. **compensating path**: 2-4 で起動失敗・例外が起きたら ``mark_terminal(failed)`` で行を
         terminalize し orphan 行を残さない。生存 process が残っていれば killpg で kill。
      6. **concurrent terminalize 防御 (MEDIUM-2)**: ``mark_running`` が False (= spawning 行が
         concurrent terminalize で既に terminal 化済み = DB 上 kill 対象外) を返したら、起動済み
         live process を **killpg(SIGKILL) で即 kill** し、``_active_agents`` に登録せず例外を raise
         する。これを怠ると「DB 行 terminal + live process 生存」の unkillable orphan が残る。

    呼出側は advisory lock + 同一 transaction を本関数の前後で保持し commit する (A-1 §3、commit で
    lock 解放 → lock 外 child 起動の窓を塞ぐ)。本関数は commit しない (transaction 境界は caller)。
    """
    resolved_host = host_id or default_host_id()

    # (1) latch check (B2 は no-op stub、B3 で fail-closed 本体)。
    await _assert_not_emergency_stopped(tenant_id)

    # (2) process 起動前に spawning 行を pre-register。
    managed_id = await registry.register_spawning(
        tenant_id=tenant_id,
        project_id=project_id,
        host_id=resolved_host,
        agent_run_id=agent_run_id,
        supervisor_id=supervisor_id,
    )

    proc: asyncio.subprocess.Process | None = None
    try:
        # (3) process 起動。
        proc = await _start_subprocess(provider, project_dir)
        pgid = os.getpgid(proc.pid)
        boot_id = get_host_boot_id()
        # (4) pid/pgid/boot_id 確定 → running。spawning 行のみ遷移可 (rowcount=1 で True)。
        marked_running = await registry.mark_running(
            tenant_id=tenant_id,
            managed_agent_id=managed_id,
            pid=proc.pid,
            process_group_id=pgid,
            boot_id=boot_id,
        )
        if not marked_running:
            # (6) concurrent terminalize: spawning 行が既に terminal 化済み (DB 上 kill 対象外)。
            # live process を始末して spawn を abort する (unkillable orphan を作らない)。
            raise ManagedAgentTerminalizedDuringSpawn(managed_id)
    except BaseException:
        # (5)/(6) compensating: orphan 行を残さない。生存 process は killpg で kill。
        if proc is not None and proc.returncode is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
        try:
            await registry.mark_terminal(
                tenant_id=tenant_id,
                managed_agent_id=managed_id,
                state="failed",
            )
        except Exception:  # noqa: BLE001 - terminalize 失敗は元例外を握り潰さない
            logger.warning(
                "managed_agent_compensating_terminalize_failed",
                extra={"managed_agent_id": str(managed_id), "host_id": resolved_host},
            )
        raise

    agent = SpawnedAgent(
        agent_id=agent_id,
        provider=provider,
        process=proc,
        pid=proc.pid,
        started_at=datetime.now(UTC),
    )
    # in-process cache = process-local handle (自 process subprocess を signal する手段)。
    # kill の正本は managed_agents (A-3)。
    _active_agents[agent_id] = agent
    return agent


def _signal_process_group(proc: asyncio.subprocess.Process, sig: int) -> None:
    """child を起動した process group 全体へ signal を送る (descendant の残留防止)。

    Codex R6 F-9: spawn_agent は ``start_new_session=True`` で child を process group leader に
    するため、stop は直接 child だけでなく group 全体を対象にする (kill_all_agents と同 semantics)。
    group 解決に失敗した場合は直接 child へ fallback する。
    """
    if proc.pid is None or proc.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), sig)
        return
    except (ProcessLookupError, OSError):
        pass
    try:
        if sig == signal.SIGKILL:
            proc.kill()
        else:
            proc.terminate()
    except ProcessLookupError:
        pass


async def stop_agent(agent_id: UUID) -> SpawnedAgent | None:
    agent = _active_agents.get(agent_id)
    if agent is None or agent.process is None:
        return agent

    proc = agent.process
    _signal_process_group(proc, signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), timeout=STOP_GRACE_SECONDS)
    except (TimeoutError, ProcessLookupError):
        _signal_process_group(proc, signal.SIGKILL)
        try:
            await proc.wait()
        except ProcessLookupError:
            pass

    agent.stopped_at = datetime.now(UTC)
    agent.exit_code = proc.returncode
    return agent


async def kill_all_agents() -> list[UUID]:
    killed = []
    for agent_id, agent in list(_active_agents.items()):
        if agent.process and agent.process.returncode is None:
            try:
                os.killpg(os.getpgid(agent.process.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            agent.stopped_at = datetime.now(UTC)
            agent.exit_code = -9
            killed.append(agent_id)
    return killed


def list_agents() -> list[dict[str, object]]:
    return [
        {
            "agent_id": str(a.agent_id),
            "provider": a.provider,
            "pid": a.pid,
            "started_at": a.started_at.isoformat() if a.started_at else None,
            "stopped_at": a.stopped_at.isoformat() if a.stopped_at else None,
            "running": a.process is not None and a.process.returncode is None,
        }
        for a in _active_agents.values()
    ]
