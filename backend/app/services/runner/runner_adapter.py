"""Sprint 7 BL-0071 (batch 1) + BL-0074/0075/0076 (batch 2): RunnerAdapter.

ADR-00003 + ADR-00008 boundary の RunnerAdapter abstract interface。Docker
integration は Sprint 11 で本実装、本 module は **interface + mock backend** を
提供し、上位 service (AgentRuntime) が runner_mutation_gateway 経由で patch
apply を行う流れを Sprint 7 内で contract test できる状態にする。

設計 (DD-01 §RunnerAdapter + Codex R1 F-001/F-003/F-007 adopt):

- ``RunnerAdapter`` は ABC で 4 method: ``prepare_workspace`` /
  ``run_command`` / ``collect_artifacts`` / ``cancel``。
- ``MockRunnerAdapter`` は in-process 実装、Docker container を使わない
  (test / dev 用)。
- container lifecycle (image pull / volume / network) は ``DockerRunnerAdapter``
  (Sprint 11 で本実装) で扱う。

server-owned-boundary §1 (Codex R1 F-007 adopt):

- ``RunnerCommandRequest`` は argv + cwd + env_allowlist の command intent のみ
  受け取り、resource_policy / network_policy は **caller-supplied 経路から
  signature レベルで削除** された。
- 代わりに ``RunnerExecutionContext`` を **server-owned** な struct として
  orchestrator が解決し、``run_command`` の必須 parameter として渡す。
- caller が任意 policy を挿入する経路がなく、orchestrator が P0 default を
  必ず適用する。
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from backend.app.services.runner.env_scrub import EnvScrubResult, scrub_env
from backend.app.services.runner.network_egress import NetworkPolicy
from backend.app.services.runner.resource_cap import ResourcePolicy


@dataclass(frozen=True, slots=True)
class RunnerWorkspace:
    """Per-run isolated workdir reference."""

    run_id: str
    workspace_id: str  # uuid hex, server-generated
    workdir: str  # absolute path, mode=0o700, uid=getuid()


@dataclass(frozen=True, slots=True)
class RunnerCommandRequest:
    """Single command invocation request (caller-supplied command intent only).

    Codex R1 F-007 adopt: resource_policy / network_policy は signature
    レベルで削除。代わりに RunnerExecutionContext を server-owned で渡す。
    """

    argv: tuple[str, ...]
    cwd: str  # must be inside RunnerWorkspace.workdir
    env_allowlist: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class RunnerExecutionContext:
    """Server-owned execution policy bundle (Codex R1 F-007 adopt).

    Orchestrator が resolve し、caller は直接 instance 生成不可。
    ``MockRunnerAdapter.run_command`` 経由でのみ受け取り、policy enforcement
    が必ず適用される。
    """

    resource_policy: ResourcePolicy
    network_policy: NetworkPolicy

    @classmethod
    def p0_default(cls) -> RunnerExecutionContext:
        """P0 default context: ResourcePolicy.from_p0_defaults() +
        NetworkPolicy.p0_default() (deny_all egress)。"""
        return cls(
            resource_policy=ResourcePolicy.from_p0_defaults(),
            network_policy=NetworkPolicy.p0_default(),
        )


@dataclass(frozen=True, slots=True)
class RunnerCommandResult:
    exit_code: int | None
    stdout_bytes: int
    stderr_bytes: int
    duration_seconds: float
    timeout_reached: bool
    cancelled: bool
    output_cap_exceeded: bool = False
    scrubbed_env_keys: tuple[str, ...] = ()
    network_deny_reason: str | None = None


@dataclass(slots=True)
class RunnerCancelToken:
    """In-process cancel signal (Sprint 6 CancelRegistry と統合可能 interface)."""

    _cancelled: bool = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled


# Codex R1 F-001 adopt: NetworkPolicy.mode=deny_all 時に明らかに network-capable
# な command を MockRunnerAdapter level で deny する。Docker network=none に
# よる本格的 enforcement は Sprint 11 で DockerRunnerAdapter が担当。
# 本 set は basename match で評価される (canonicalize_command で /usr/bin/curl
# → curl に正規化済の前提)。
_NETWORK_CAPABLE_COMMANDS: frozenset[str] = frozenset(
    {
        "curl",
        "wget",
        "ftp",
        "tftp",
        "scp",
        "sftp",
        "rsync",
        "ssh",
        "telnet",
        "nc",
        "ncat",
        "socat",
        "git",  # git clone / fetch / pull / push
        "svn",
        "hg",
        "pip",
        "pip3",
        "npm",
        "yarn",
        "pnpm",
        "cargo",
        "gem",
        "go",  # go get / go install
        "composer",
        "mvn",
        "gradle",
        "apt",
        "apt-get",
        "yum",
        "dnf",
        "pacman",
        "brew",
        "docker",
        "kubectl",
        "helm",
    }
)


def _is_network_capable_command(argv: tuple[str, ...]) -> str | None:
    """Codex R1 F-001 adopt: detect network-capable command basename.

    Returns command basename if detected, None otherwise.
    """
    if not argv:
        return None
    raw_cmd = argv[0]
    basename = os.path.basename(raw_cmd).lower()
    if basename in _NETWORK_CAPABLE_COMMANDS:
        return basename
    return None


class RunnerAdapter(ABC):
    """Abstract runner interface. Docker / Mock / Remote 実装を持つ。"""

    @abstractmethod
    async def prepare_workspace(self, run_id: str) -> RunnerWorkspace:
        """run_id 単位の isolated workdir を作る (mode=0o700)。"""

    @abstractmethod
    async def run_command(
        self,
        workspace: RunnerWorkspace,
        request: RunnerCommandRequest,
        execution_context: RunnerExecutionContext,
        cancel_token: RunnerCancelToken | None = None,
    ) -> RunnerCommandResult:
        """workspace 内で argv を実行。execution_context (server-owned) の
        resource_policy / network_policy が必ず適用される。"""

    @abstractmethod
    async def collect_artifacts(
        self,
        workspace: RunnerWorkspace,
    ) -> tuple[str, ...]:
        """workspace 内に生成された artifact path リストを返す。"""

    @abstractmethod
    async def cleanup(self, workspace: RunnerWorkspace) -> None:
        """workspace 削除 (run 完了 / cancel / timeout 後)。"""


class MockRunnerAdapter(RunnerAdapter):
    """In-process mock (Docker 不使用)。**test / dev 専用、production 禁止**。

    Codex SP7 audit F-SP7-002 adopt:

    - 本 adapter は host subprocess を直接実行するため、CPU / memory / pids /
      disk / network の **物理 isolation はない**。``ResourcePolicy`` は
      `wall_clock_seconds` と `output_byte_cap` のみ enforce、CPU/memory/pids
      の cgroups 制約は **適用されない**。
    - production runtime には使わない。SP-007 §目的 の Docker isolation 要件は
      Sprint 11 の ``DockerRunnerAdapter`` 実装で達成する (Docker network=none +
      cgroups + iptables + read-only root + non-root + no Docker socket +
      no host network + bounded mounts)。
    - 上位 service (AgentRuntime) は production 経路では DockerRunnerAdapter
      を選択する責任を持つ。MockRunnerAdapter を production 経路で使うと
      cancel watcher 等の concurrent test が動作しても、実 attack surface
      (fork bomb / zip bomb / memory leak) は kernel-level の保護を持たない。

    Sprint 7 batch 1 / batch 2 では integration test の代用、Sprint 11 で
    DockerRunnerAdapter に置換。
    """

    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = base_dir or tempfile.gettempdir()
        self._workspaces: dict[str, str] = {}

    async def prepare_workspace(self, run_id: str) -> RunnerWorkspace:
        workspace_id = uuid.uuid4().hex
        workdir = Path(self._base_dir) / f"runner-{run_id}-{workspace_id}"
        workdir.mkdir(parents=True, exist_ok=False, mode=0o700)
        self._workspaces[workspace_id] = str(workdir)
        return RunnerWorkspace(
            run_id=run_id,
            workspace_id=workspace_id,
            workdir=str(workdir),
        )

    async def run_command(  # noqa: C901, PLR0912, PLR0915 - inherent complexity
        self,
        workspace: RunnerWorkspace,
        request: RunnerCommandRequest,
        execution_context: RunnerExecutionContext,
        cancel_token: RunnerCancelToken | None = None,
    ) -> RunnerCommandResult:
        if not request.argv:
            raise ValueError("argv must be non-empty")

        # Codex SP7 R1 F-003 adopt: dangerous command gate を入口で必ず適用。
        from backend.app.services.runner.dangerous_command import (  # noqa: PLC0415
            detect_dangerous_command,
        )

        violation = detect_dangerous_command(request.argv)
        if violation is not None:
            # Codex SP7 audit F-SP7-009 adopt: raw argv は exception message に
            # 含めない (AC-HARD-02 invariant 維持)。debug-only な詳細は別 channel
            # (build_runner_blocked audit) で記録、上位 caller は reason_code +
            # argv basename のみを user / log に出す。
            import hashlib  # noqa: PLC0415

            argv_hash = hashlib.sha256(
                "\x00".join(request.argv).encode("utf-8")
            ).hexdigest()[:16]
            argv_basename = (
                os.path.basename(request.argv[0]) if request.argv else ""
            )
            raise ValueError(
                f"runner_blocked: dangerous_command "
                f"reason={violation.reason.value} "
                f"argv_basename={argv_basename} argv_hash={argv_hash}"
            )

        # Codex R1 F-001 adopt: network_policy enforcement。
        # NetworkPolicy.mode=deny_all 時に明らかに network-capable な command を
        # deny。完全 enforcement は Sprint 11 Docker network=none で実装。
        from backend.app.services.runner.network_egress import (  # noqa: PLC0415
            NetworkEgressMode,
        )

        network_deny_reason: str | None = None
        if execution_context.network_policy.mode == NetworkEgressMode.DENY_ALL:
            net_cmd = _is_network_capable_command(request.argv)
            if net_cmd is not None:
                raise ValueError(
                    f"runner_blocked: network_egress "
                    f"reason=mode_deny_all_network_capable_command "
                    f"command={net_cmd}"
                )

        # Codex R1 F-007 adopt: server-owned resource_policy validate。
        cap_violations = execution_context.resource_policy.validate()
        if cap_violations:
            reasons = ",".join(v.value for v in cap_violations)
            raise ValueError(f"runner_blocked: resource_cap reasons={reasons}")

        # Codex SP7 R1 F-006 adopt: cwd containment は ``Path.resolve()`` 後の
        # canonical compare で symlink follow 後の escape を物理削除。
        # Codex SP7 R2 F-SP7-R2-001 adopt: cwd / resolved path / OSError message を
        # exception text から削除、workspace_id + cwd_hash のみ含める。
        import hashlib as _hashlib  # noqa: PLC0415

        workdir_resolved = await asyncio.to_thread(
            lambda: str(Path(workspace.workdir).resolve(strict=False))
        )
        try:
            cwd_resolved = await asyncio.to_thread(
                lambda: str(Path(request.cwd).resolve(strict=False))
            )
        except OSError as exc:
            cwd_hash = _hashlib.sha256(request.cwd.encode("utf-8")).hexdigest()[:16]
            raise ValueError(
                f"runner_blocked: cwd_resolve_failed "
                f"workspace_id={workspace.workspace_id} cwd_hash={cwd_hash} "
                f"errno={getattr(exc, 'errno', 'unknown')}"
            ) from exc
        if not (
            cwd_resolved == workdir_resolved
            or cwd_resolved.startswith(workdir_resolved + os.sep)
        ):
            cwd_hash = _hashlib.sha256(request.cwd.encode("utf-8")).hexdigest()[:16]
            raise ValueError(
                f"runner_blocked: cwd_outside_workspace "
                f"workspace_id={workspace.workspace_id} cwd_hash={cwd_hash}"
            )

        # Sprint 7 batch 2 BL-0076: env scrub を ``env_scrub`` module に
        # 切り出し。70+ var hardcode + pattern (Codex R1 F-004 adopt 拡張)。
        scrub_result: EnvScrubResult = scrub_env(request.env_allowlist)
        env = scrub_result.env

        # Codex R1 F-003 adopt: wall_clock_seconds を resource_policy 単一 source に。
        # RunnerCommandRequest.timeout_seconds は signature から削除済み。
        timeout_s = execution_context.resource_policy.wall_clock_seconds

        loop = asyncio.get_running_loop()
        start = loop.time()
        proc = await asyncio.create_subprocess_exec(
            *request.argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=request.cwd,
            env=env,
            start_new_session=True,
        )

        timeout_reached = False
        cancelled = False
        output_cap_exceeded = False
        # Codex SP7 R2 F-SP7-R2-002 adopt: output_cap_event で cap 超過を
        # gather/cancel watcher と並列に detect、即時 kill 経路を提供
        output_cap_event = asyncio.Event()

        # Codex SP7 R1 F-010 adopt: process group SIGTERM -> SIGKILL escalation。
        async def _terminate_process_group() -> None:
            if proc.returncode is not None:
                return
            try:
                pgid = os.getpgid(proc.pid)
            except (ProcessLookupError, PermissionError):
                pgid = None
            try:
                if pgid is not None and hasattr(os, "killpg"):
                    os.killpg(pgid, signal.SIGTERM)
                else:
                    proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except TimeoutError:
                try:
                    if pgid is not None and hasattr(os, "killpg"):
                        os.killpg(pgid, signal.SIGKILL)
                    else:
                        proc.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except TimeoutError:
                    pass

        # Codex R1 F-003 adopt: chunk read + output_byte_cap での real-time kill。
        # 各 stream を chunk 単位で読み、stdout_byte_cap / stderr_byte_cap /
        # output_byte_cap (合計) のいずれか超過時点で process group を kill。
        stdout_buf = bytearray()
        stderr_buf = bytearray()
        rp = execution_context.resource_policy

        async def _drain_stream(
            stream: asyncio.StreamReader | None,
            buffer: bytearray,
            per_stream_cap: int,
        ) -> None:
            """Read stream chunk-by-chunk; trigger output cap event if exceeded.

            Codex SP7 R2 F-SP7-R2-002 adopt: cap 超過時に output_cap_event.set()
            して gather/cancel watcher と並列に detect、即時 kill 経路を起動。
            """
            nonlocal output_cap_exceeded
            if stream is None:
                return
            chunk_size = 64 * 1024  # 64 KiB chunks
            while True:
                try:
                    chunk = await stream.read(chunk_size)
                except (asyncio.CancelledError, ConnectionResetError):
                    return
                if not chunk:
                    return
                buffer.extend(chunk)
                # Check per-stream cap
                if len(buffer) > per_stream_cap:
                    output_cap_exceeded = True
                    output_cap_event.set()
                    return
                # Check total cap
                if len(stdout_buf) + len(stderr_buf) > rp.output_byte_cap:
                    output_cap_exceeded = True
                    output_cap_event.set()
                    return

        drain_stdout = asyncio.create_task(
            _drain_stream(proc.stdout, stdout_buf, rp.stdout_byte_cap)
        )
        drain_stderr = asyncio.create_task(
            _drain_stream(proc.stderr, stderr_buf, rp.stderr_byte_cap)
        )

        # Codex SP7 audit F-SP7-005 adopt: cancel watcher を concurrent に走らせ、
        # proc.wait() 完了を待つ前に cancel signal が来た時点で process group を
        # kill する。従来は proc.wait() 完了/timeout/output cap 後にしか cancel
        # を見ず、長時間 process が timeout まで残る問題があった。
        cancel_event = asyncio.Event()

        async def _cancel_watcher() -> None:
            """100 ms polling で cancel_token を監視、signal 到達で event set。"""
            if cancel_token is None:
                # cancel_token なしの場合は永久 sleep (gather で他 task 完了待ち)
                await asyncio.sleep(timeout_s + 5.0)
                return
            poll_interval = 0.1
            while not cancel_token.is_cancelled:
                if proc.returncode is not None:
                    return
                await asyncio.sleep(poll_interval)
            cancel_event.set()

        watcher_task = asyncio.create_task(_cancel_watcher())

        async def _gather_proc() -> None:
            await asyncio.gather(drain_stdout, drain_stderr, proc.wait())

        gather_task = asyncio.create_task(_gather_proc())

        # Codex SP7 R2 F-SP7-R2-002 adopt: output_cap_event を FIRST_COMPLETED
        # の対象に追加し、cap 超過時に gather や watcher を待たず即時 kill 経路へ
        async def _output_cap_waiter() -> None:
            await output_cap_event.wait()

        output_cap_task = asyncio.create_task(_output_cap_waiter())

        try:
            done, _pending = await asyncio.wait(
                {gather_task, watcher_task, output_cap_task},
                timeout=timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                # all timed out
                timeout_reached = True
        except TimeoutError:
            timeout_reached = True

        # Codex SP7 R2 F-SP7-R2-002: output cap event set → 即時 kill
        if output_cap_event.is_set() and proc.returncode is None:
            await _terminate_process_group()

        # Cancel signal received during run → kill process group
        if cancel_event.is_set() and proc.returncode is None:
            cancelled = True
            await _terminate_process_group()

        # Timeout → kill process group
        if timeout_reached and proc.returncode is None:
            await _terminate_process_group()

        # Cleanup remaining tasks (drain + watcher + output_cap_waiter)
        for task in (drain_stdout, drain_stderr, watcher_task, gather_task, output_cap_task):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110
                    pass

        # Codex R1 F-003 adopt: output cap detected during stream drain → kill (safety net)
        if output_cap_exceeded and proc.returncode is None:
            await _terminate_process_group()

        # cancel_token を再チェック (cancel_event set 経路と watcher 完了経路の両方)
        if cancel_token is not None and cancel_token.is_cancelled:
            cancelled = True
            if proc.returncode is None:
                await _terminate_process_group()

        return RunnerCommandResult(
            exit_code=proc.returncode,
            stdout_bytes=len(stdout_buf),
            stderr_bytes=len(stderr_buf),
            duration_seconds=loop.time() - start,
            timeout_reached=timeout_reached,
            cancelled=cancelled,
            output_cap_exceeded=output_cap_exceeded,
            scrubbed_env_keys=scrub_result.scrubbed_keys,
            network_deny_reason=network_deny_reason,
        )

    async def collect_artifacts(
        self,
        workspace: RunnerWorkspace,
    ) -> tuple[str, ...]:
        return await asyncio.to_thread(_collect_files_sync, workspace.workdir)

    async def cleanup(self, workspace: RunnerWorkspace) -> None:
        path = self._workspaces.pop(workspace.workspace_id, None)
        if path is not None:
            await asyncio.to_thread(shutil.rmtree, path, True)


def _collect_files_sync(workdir: str) -> tuple[str, ...]:
    """Sync helper for ``MockRunnerAdapter.collect_artifacts`` (run in thread)."""

    base = Path(workdir)
    if not base.is_dir():
        return ()
    return tuple(str(p) for p in base.rglob("*") if p.is_file())


# Suppress unused import warning for re (kept for future regex use)
_ = re


__all__ = [
    "MockRunnerAdapter",
    "RunnerAdapter",
    "RunnerCancelToken",
    "RunnerCommandRequest",
    "RunnerCommandResult",
    "RunnerExecutionContext",
    "RunnerWorkspace",
]
