"""Sprint 6 batch 2: CliInvocationOrchestrator - high-level wiring.

ADR-00003 §A boundary の CliArtifactAdapter。Sprint 6 batch 1 で実装した
``launch_cli_agent`` を call し、batch 2 で追加した redaction / per-run workdir
/ exit_mapping / cancel_propagation を統合する。

責務 (本 module は domain-pure):

1. 入力: ``CliInvocationRequest`` (agent_name + run_id + tenant_id +
   prompt_bytes + redacted_prompt_data_class + actor_id)。
2. server-owned per-run artifact workdir を作成 (R3-003 完全対策)。
3. prompt を atomically write (O_CREAT|O_EXCL|O_NOFOLLOW)。
4. ``launch_cli_agent`` を呼ぶ。``CancelRegistry.wait_for_cancel`` と race。
5. cancel 発火時は task.cancel() で launcher 内 ``_terminate_with_grace`` を
   trigger (SIGTERM → SIGKILL process group)。
6. subprocess 完了後、output / stream を read → redaction pipeline。
7. ``map_launcher_result`` で AgentRun status mapping。
8. ``build_cli_process_completed_payload`` で event payload を build。
9. ``CliInvocationOutcome`` を返す (orchestrator caller = AgentRuntime が
   AgentRunEvent / artifact 永続化を担当)。

**Caller contract (Codex SP6B2 R1 F-008 MEDIUM partial adopt)**:

本 module は AgentRunEvent / artifact 永続化を **行わない**。caller (Sprint 6
batch 3 で実装される ``AgentRuntime.execute_cli_invocation_step()`` 相当の
wrapper) は次を **必ず** 同一 transaction で行うこと:

- ``CliInvocationOutcome.completed_event_payload`` を AgentRunEvent
  (event_type=``cli_process_completed``) として append。
- ``CliInvocationOutcome.workdir`` 配下の artifact (``cli_input`` /
  ``cli_stdout`` / ``cli_stderr`` / ``cli_exit``) を artifact store へ
  persist。
- ``CliInvocationOutcome.exit_mapping`` の ``next_status`` + ``blocked_reason``
  を AgentRun status / blocked_reason に反映。

これらは Sprint 6 batch 3 で **contract test** として fail-fast 化される
(現状は本 docstring + cli_artifact_orchestration smoke test の暗黙 contract)。

server-owned-boundary §1 不変条件:

- ``CliInvocationRequest`` から path / cwd / output_file 等の caller-supplied
  fs path を受けない。すべて per_run_workdir で server-side 生成。
- prompt bytes は raw 値だが、redaction pipeline は subprocess output に対し
  ても scan する (defense-in-depth)。schema 層 (CliArtifactPayload) で raw
  secret scan 済の content を渡す前提。
- DB / artifact store / audit event の永続化は orchestrator caller の責任。
  本 module はメモリ上の outcome を返すだけ。

呼び出し例 (本 batch では未使用、Sprint 6 batch 3 wiring で利用):

    orchestrator = CliInvocationOrchestrator(
        registry=load_cli_agent_registry("config/cli_registry.toml"),
        cancel_registry=CancelRegistry(),
    )
    outcome = await orchestrator.invoke(request)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from backend.app.services.cli_artifact.cancel_propagation import (
    CancelKey,
    CancelRegistry,
)
from backend.app.services.cli_artifact.exit_mapping import (
    CliExitOutcome,
    CliProcessCompletedPayload,
    ExitMappingDecision,
    build_cli_process_completed_payload,
    map_launcher_result,
)
from backend.app.services.cli_artifact.launcher import (
    LauncherError,
    LauncherResult,
    LauncherRunRequest,
    launch_cli_agent,
)
from backend.app.services.cli_artifact.per_run_workdir import (
    PerRunWorkdir,
    allocate_workdir,
    write_prompt_atomically,
)
from backend.app.services.cli_artifact.redaction import (
    RedactionResult,
    redact_stream,
)
from backend.app.services.cli_artifact.registry import CliAgentRegistry


@dataclass(frozen=True, slots=True)
class CliInvocationRequest:
    """High-level invocation request (server-owned signature)."""

    agent_name: str
    tenant_id: str
    run_id: str
    actor_id: str
    prompt_bytes: bytes
    artifact_workdir_base: str


@dataclass(frozen=True, slots=True)
class CliInvocationOutcome:
    """Result of a single CLI invocation (raw 値非含)."""

    workdir: PerRunWorkdir
    launcher_result: LauncherResult | None  # LauncherError 時 None
    launcher_error_reason: str | None  # LauncherDenyReason.value or None
    stdout_redaction: RedactionResult | None
    stderr_redaction: RedactionResult | None
    exit_mapping: ExitMappingDecision | None
    completed_event_payload: CliProcessCompletedPayload | None
    cancelled_via_registry: bool


@dataclass(slots=True)
class CliInvocationOrchestrator:
    registry: CliAgentRegistry
    cancel_registry: CancelRegistry

    async def invoke(
        self,
        request: CliInvocationRequest,
    ) -> CliInvocationOutcome:
        cancel_key = CancelKey(tenant_id=request.tenant_id, run_id=request.run_id)

        # Codex SP6B2 R1 F-002 (HIGH) adopt: launcher cwd allowlist 検査を
        # workdir 作成 + prompt 書き込みの **前** に行う。これにより
        # ``artifact_workdir_base`` が registry の cwd_allowlist 配下に存在し
        # ない場合、prompt bytes が forbidden path に書かれる経路を物理削除。
        entry = self.registry.get(request.agent_name)
        if not _base_dir_inside_allowlist(
            base_dir=request.artifact_workdir_base,
            allowlist=entry.cwd_allowlist,
        ):
            return CliInvocationOutcome(
                workdir=_EMPTY_WORKDIR,
                launcher_result=None,
                launcher_error_reason="artifact_workdir_outside_allowlist",
                stdout_redaction=None,
                stderr_redaction=None,
                exit_mapping=None,
                completed_event_payload=None,
                cancelled_via_registry=False,
            )

        workdir = allocate_workdir(
            run_id=request.run_id,
            base_dir=request.artifact_workdir_base,
        )
        write_prompt_atomically(workdir, request.prompt_bytes)

        # cancel が既に発火していたら launcher を起動しない (workdir は残るが
        # caller / GC が cleanup 担当)
        if self.cancel_registry.is_cancelled(cancel_key):
            self.cancel_registry.unregister(cancel_key)
            stdout_redaction, stderr_redaction = _drain_artifact_streams(
                workdir, entry
            )
            return CliInvocationOutcome(
                workdir=workdir,
                launcher_result=None,
                launcher_error_reason="cancelled_before_launch",
                stdout_redaction=stdout_redaction,
                stderr_redaction=stderr_redaction,
                exit_mapping=None,
                completed_event_payload=None,
                cancelled_via_registry=True,
            )

        launcher_request = LauncherRunRequest(
            agent_name=request.agent_name,
            prompt_file=workdir.prompt_file,
            output_file=workdir.output_file,
            stream_file=workdir.stream_file,
            cwd=workdir.workdir,
        )

        launch_task = asyncio.create_task(
            launch_cli_agent(launcher_request, self.registry)
        )
        cancel_task = asyncio.create_task(
            self.cancel_registry.wait_for_cancel(cancel_key)
        )

        try:
            done, _pending = await asyncio.wait(
                {launch_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            self.cancel_registry.unregister(cancel_key)

        cancelled_via_registry = False
        if cancel_task in done and launch_task not in done:
            cancelled_via_registry = True
            launch_task.cancel()
            try:
                await launch_task
            except (asyncio.CancelledError, LauncherError):
                pass

        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass

        if launch_task.cancelled():
            # Codex SP6B2 R1 F-003 (HIGH) adopt: cancel 経路でも output /
            # stream を read + redaction し、partial CLI output を audit へ
            # 流す。これにより cancel 前の subprocess 出力が観測 (audit)
            # から完全消失する経路を塞ぐ。
            stdout_redaction, stderr_redaction = _drain_artifact_streams(
                workdir, entry
            )
            return CliInvocationOutcome(
                workdir=workdir,
                launcher_result=None,
                launcher_error_reason="cancelled_during_launch",
                stdout_redaction=stdout_redaction,
                stderr_redaction=stderr_redaction,
                exit_mapping=None,
                completed_event_payload=None,
                cancelled_via_registry=True,
            )

        exc = launch_task.exception()
        if exc is not None:
            if isinstance(exc, LauncherError):
                return CliInvocationOutcome(
                    workdir=workdir,
                    launcher_result=None,
                    launcher_error_reason=exc.reason.value,
                    stdout_redaction=None,
                    stderr_redaction=None,
                    exit_mapping=None,
                    completed_event_payload=None,
                    cancelled_via_registry=cancelled_via_registry,
                )
            raise exc

        launcher_result: LauncherResult = launch_task.result()
        stdout_redaction = _read_and_redact(
            Path(workdir.output_file),
            max_bytes=self.registry.get(request.agent_name).max_stdout_bytes,
        )
        stderr_redaction = _read_and_redact(
            Path(workdir.stream_file),
            max_bytes=self.registry.get(request.agent_name).max_stderr_bytes,
        )

        exit_mapping = map_launcher_result(launcher_result)
        # cancel_registry 由来で kill した場合は outcome を CANCELLED に上書き
        if cancelled_via_registry:
            exit_mapping = ExitMappingDecision(
                outcome=CliExitOutcome.CANCELLED,
                next_status="cancelled",
                blocked_reason=None,
                is_terminal=True,
            )

        completed_event_payload = build_cli_process_completed_payload(
            result=launcher_result,
            stdout_redaction=stdout_redaction,
            stderr_redaction=stderr_redaction,
            outcome=exit_mapping.outcome,
        )

        return CliInvocationOutcome(
            workdir=workdir,
            launcher_result=launcher_result,
            launcher_error_reason=None,
            stdout_redaction=stdout_redaction,
            stderr_redaction=stderr_redaction,
            exit_mapping=exit_mapping,
            completed_event_payload=completed_event_payload,
            cancelled_via_registry=cancelled_via_registry,
        )


_EMPTY_WORKDIR = PerRunWorkdir(
    workdir="",
    prompt_file="",
    output_file="",
    stream_file="",
    launch_id="",
)


def _base_dir_inside_allowlist(
    *,
    base_dir: str,
    allowlist: tuple[str, ...],
) -> bool:
    """artifact_workdir_base が registry の cwd_allowlist 配下にあるか."""

    if not base_dir or not base_dir.startswith("/"):
        return False
    try:
        resolved = str(Path(base_dir).resolve(strict=False))
    except OSError:
        return False
    import os as _os  # noqa: PLC0415

    for base in allowlist:
        base_resolved = str(Path(base).resolve(strict=False))
        if resolved == base_resolved or resolved.startswith(base_resolved + _os.sep):
            return True
    return False


def _drain_artifact_streams(
    workdir: PerRunWorkdir,
    entry: object,
) -> tuple[RedactionResult, RedactionResult]:
    """workdir の output / stream を read + redaction する."""

    # entry は AgentRegistryEntry だが循環 import 防止のため object 受け取り
    max_stdout = int(getattr(entry, "max_stdout_bytes", 1024 * 1024))
    max_stderr = int(getattr(entry, "max_stderr_bytes", 512 * 1024))
    if workdir.output_file:
        stdout_redaction = _read_and_redact(
            Path(workdir.output_file), max_bytes=max_stdout
        )
    else:
        stdout_redaction = redact_stream(b"", max_bytes=max_stdout)
    if workdir.stream_file:
        stderr_redaction = _read_and_redact(
            Path(workdir.stream_file), max_bytes=max_stderr
        )
    else:
        stderr_redaction = redact_stream(b"", max_bytes=max_stderr)
    return stdout_redaction, stderr_redaction


def _read_and_redact(path: Path, *, max_bytes: int) -> RedactionResult:
    """File から bytes を読み redaction pipeline に通す。

    O_RDONLY|O_NOFOLLOW で open し、parent-swap race を狭める。max_bytes
    超過は redaction pipeline が truncate を記録。
    """

    import os  # noqa: PLC0415

    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    fd = os.open(str(path), flags)
    try:
        with os.fdopen(fd, "rb") as fp:
            raw = fp.read(max_bytes + 1)  # +1 で truncation を確実に検出
    except OSError:
        raw = b""
    return redact_stream(raw, max_bytes=max_bytes)


__all__ = [
    "CliInvocationOrchestrator",
    "CliInvocationOutcome",
    "CliInvocationRequest",
]
