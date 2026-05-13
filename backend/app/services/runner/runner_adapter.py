"""Sprint 7 BL-0071: RunnerAdapter (Docker isolated runner interface).

ADR-00003 + ADR-00008 boundary の RunnerAdapter abstract interface。Docker
integration は Sprint 11 で本実装、本 module は **interface + mock backend** を
提供し、上位 service (AgentRuntime) が runner_mutation_gateway 経由で patch
apply を行う流れを Sprint 7 内で contract test できる状態にする。

設計 (DD-01 §RunnerAdapter):

- ``RunnerAdapter`` は ABC で 4 method: ``prepare_workspace`` /
  ``run_command`` / ``collect_artifacts`` / ``cancel``。
- ``MockRunnerAdapter`` は in-process 実装、Docker container を使わない
  (test / dev 用)。
- container lifecycle (image pull / volume / network) は ``DockerRunnerAdapter``
  (Sprint 11 で本実装) で扱う。
- Sprint 7 batch 1 では mock のみ実装し、enforce_runner_mutation_gateway の
  contract が成立することを test で証明。

server-owned-boundary §1:

- ``RunnerCommandRequest`` は argv + cwd + timeout のみで、shell string や
  raw env を caller から受け取らない (env scrub は Sprint 6 batch 1 と同じ
  pattern で adapter 内で行う)。
- ``RunnerWorkspace`` の workdir は server-side で uuid 生成 (mock では
  ``tempfile.TemporaryDirectory``)。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunnerWorkspace:
    """Per-run isolated workdir reference."""

    run_id: str
    workspace_id: str  # uuid hex, server-generated
    workdir: str  # absolute path, mode=0o700, uid=getuid()


@dataclass(frozen=True, slots=True)
class RunnerCommandRequest:
    """Single command invocation request."""

    argv: tuple[str, ...]
    cwd: str  # must be inside RunnerWorkspace.workdir
    env_allowlist: frozenset[str] = field(default_factory=frozenset)
    timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class RunnerCommandResult:
    exit_code: int | None
    stdout_bytes: int
    stderr_bytes: int
    duration_seconds: float
    timeout_reached: bool
    cancelled: bool


@dataclass(slots=True)
class RunnerCancelToken:
    """In-process cancel signal (Sprint 6 CancelRegistry と統合可能 interface)."""

    _cancelled: bool = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled


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
        cancel_token: RunnerCancelToken | None = None,
    ) -> RunnerCommandResult:
        """workspace 内で argv を実行。timeout / cancel 対応。"""

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
    """In-process mock (Docker 不使用)。test / dev 用。

    実 runner と同じ method signature を持つが、command 実行は
    ``asyncio.create_subprocess_exec`` で host 上で行う。
    Sprint 7 batch 1 では integration test の代用、Sprint 11 で
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

    async def run_command(
        self,
        workspace: RunnerWorkspace,
        request: RunnerCommandRequest,
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
            raise ValueError(
                f"runner_blocked: dangerous_command "
                f"reason={violation.reason.value} argv={request.argv!r}"
            )

        # Codex SP7 R1 F-006 adopt: cwd containment は ``Path.resolve()`` 後の
        # canonical compare で symlink follow 後の escape を物理削除。
        # asyncio.to_thread で sync Path ops を offload (ASYNC240 準拠)。
        workdir_resolved = await asyncio.to_thread(
            lambda: str(Path(workspace.workdir).resolve(strict=False))
        )
        try:
            cwd_resolved = await asyncio.to_thread(
                lambda: str(Path(request.cwd).resolve(strict=False))
            )
        except OSError as exc:
            raise ValueError(f"cwd resolve failed: {exc}") from exc
        if not (
            cwd_resolved == workdir_resolved
            or cwd_resolved.startswith(workdir_resolved + os.sep)
        ):
            raise ValueError(
                f"cwd {request.cwd!r} (resolved={cwd_resolved!r}) must be "
                f"inside workspace {workdir_resolved!r}"
            )

        # env scrub (Sprint 6 launcher registry._FORBIDDEN_ENV_NAMES と同等
        # 14 種、drift 防止)
        forbidden = {
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GITHUB_TOKEN",
            "GH_TOKEN",
            "TAILSCALE_AUTHKEY",
            "SOPS_AGE_KEY",
            "SOPS_AGE_KEY_FILE",
            "AGE_PRIVATE_KEY",
            "AGE_SECRET_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "DATABASE_URL",
            "POSTGRES_PASSWORD",
            "REDIS_PASSWORD",
            "TASKMANAGEDAI_DATABASE_URL",
            "GITHUB_APP_PRIVATE_KEY",
            "GITHUB_INSTALLATION_TOKEN",
            "OPENAI_ORG_ID",
            "HUGGINGFACE_TOKEN",
            "HF_TOKEN",
            "STRIPE_KEY",
            "STRIPE_SECRET_KEY",
            "SLACK_TOKEN",
            "SLACK_WEBHOOK_URL",
            "JWT_SECRET",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_ANON_KEY",
            "REDIS_URL",
            # Codex SP7 R1 F-009 adopt: code-loading / credential-adjacent /
            # shell startup env を deny。caller が allowlist に入れても
            # subprocess には渡らない fail-closed。
            "PYTHONPATH",
            "PYTHONSTARTUP",
            "PYTHONHOME",
            "BASH_ENV",
            "ENV",
            "ZDOTDIR",
            "LD_PRELOAD",
            "LD_LIBRARY_PATH",
            "DYLD_LIBRARY_PATH",
            "DYLD_INSERT_LIBRARIES",
            "DYLD_FALLBACK_LIBRARY_PATH",
            "SSH_AUTH_SOCK",
            "SSH_AGENT_PID",
            "GIT_CONFIG_GLOBAL",
            "GIT_CONFIG_SYSTEM",
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_EXEC_PATH",
            "GIT_SSH",
            "GIT_SSH_COMMAND",
        }
        env: dict[str, str] = {
            k: os.environ[k]
            for k in request.env_allowlist
            if k in os.environ and k not in forbidden
        }
        env.setdefault("PATH", "/usr/bin:/bin")

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

        # Codex SP7 R1 F-010 adopt: process group SIGTERM -> SIGKILL escalation。
        # ``start_new_session=True`` を活かし、child fork (background &) も
        # 含めて kill する。Sprint 6 batch 1 launcher と同じ pattern。
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

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=request.timeout_seconds,
            )
        except TimeoutError:
            timeout_reached = True
            await _terminate_process_group()
            stdout, stderr = b"", b""
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), 2.0)
            except TimeoutError:
                stdout, stderr = b"", b""
        finally:
            if cancel_token is not None and cancel_token.is_cancelled:
                cancelled = True

        return RunnerCommandResult(
            exit_code=proc.returncode,
            stdout_bytes=len(stdout),
            stderr_bytes=len(stderr),
            duration_seconds=loop.time() - start,
            timeout_reached=timeout_reached,
            cancelled=cancelled,
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
    """Sync helper for ``MockRunnerAdapter.collect_artifacts`` (run in thread).

    sync Path ops を asyncio loop で安全に実行するため thread offload。
    """

    base = Path(workdir)
    if not base.is_dir():
        return ()
    return tuple(str(p) for p in base.rglob("*") if p.is_file())


__all__ = [
    "MockRunnerAdapter",
    "RunnerAdapter",
    "RunnerCancelToken",
    "RunnerCommandRequest",
    "RunnerCommandResult",
    "RunnerWorkspace",
]
