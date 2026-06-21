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
from backend.app.services.cli_artifact.credential_canary import (
    scan_for_credential_exfiltration,
)
from backend.app.services.cli_artifact.exit_mapping import (
    CliExitOutcome,
    CliProcessCompletedPayload,
    ExitMappingDecision,
    build_cli_process_completed_payload,
    map_launcher_result,
)
from backend.app.services.cli_artifact.launcher import (
    LauncherDenyReason,
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
    # SP-PHASE0 gate C (control 1): credential exfiltration canary hit 種別
    # (raw 値非含、launcher が ``CREDENTIAL_EXFILTRATION`` を raise した場合のみ
    # 非空)。caller (AgentRuntime) が audit event に hit 種別だけ記録する。
    credential_canary_hit_kinds: tuple[str, ...] = ()


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
            # subprocess 未起動で output 空のため canary hit は通常ないが、同 helper
            # 経由で uniform に scan する (空→hit なし、無害)。
            stdout_redaction, stderr_redaction, canary_hits = (
                _drain_artifact_streams(workdir, entry)
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
                credential_canary_hit_kinds=canary_hits,
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
            #
            # SP-PHASE0 gate C (Codex adversarial HIGH sibling-path fix): cancel
            # path は launcher の canary scan を通らない (CancelledError が scan
            # より前に raise される) ため、malicious CLI が cancel race 中に
            # credential を output_file (--output-last-message) へ echo していると
            # narrow ``redact_stream`` で raw が survive する経路があった。
            # ``_drain_artifact_streams`` 自体に canary scan を組み込んだことで、
            # hit があれば withheld placeholder を返し fail-closed になる。
            stdout_redaction, stderr_redaction, canary_hits = (
                _drain_artifact_streams(workdir, entry)
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
                credential_canary_hit_kinds=canary_hits,
            )

        exc = launch_task.exception()
        if exc is not None:
            if isinstance(exc, LauncherError):
                hit_kinds = tuple(
                    sorted({h.pattern_kind for h in exc.canary_hits})
                )
                if exc.reason is LauncherDenyReason.CREDENTIAL_EXFILTRATION:
                    # SP-PHASE0 gate C (Codex adversarial HIGH 2 fix, true
                    # fail-closed): the captured output contains a credential.
                    # **Do NOT re-read + re-redact the raw artifact files** — the
                    # redaction pipeline uses the narrower ``_RAW_SECRET_PATTERNS``
                    # (no JWT / codex_refresh_token / key-name canary) so the raw
                    # credential would survive redaction and land in
                    # ``redacted_text`` + ``content_hash`` → persisted by the
                    # caller (AC-HARD-02 violation). Instead emit fixed
                    # ``[withheld: credential_exfiltration]`` placeholders with
                    # hit-kind metadata only. The raw artifact files on disk are
                    # the caller's responsibility to quarantine / not persist.
                    withheld = _withheld_redaction()
                    return CliInvocationOutcome(
                        workdir=workdir,
                        launcher_result=None,
                        launcher_error_reason=exc.reason.value,
                        stdout_redaction=withheld,
                        stderr_redaction=withheld,
                        exit_mapping=None,
                        completed_event_payload=None,
                        cancelled_via_registry=cancelled_via_registry,
                        credential_canary_hit_kinds=hit_kinds,
                    )
                # Other pre/post-launch denies (registry deny, binary not found,
                # path forbidden, etc.) did not arise from a malicious agent
                # echoing a credential, so reading + redacting partial output for
                # the audit trail is safe. ``_drain_artifact_streams`` now also
                # canary-scans (defense-in-depth) and withholds on any hit.
                stdout_redaction, stderr_redaction, drain_hits = (
                    _drain_artifact_streams(workdir, entry)
                )
                merged_hits = tuple(sorted(set(hit_kinds) | set(drain_hits)))
                return CliInvocationOutcome(
                    workdir=workdir,
                    launcher_result=None,
                    launcher_error_reason=exc.reason.value,
                    stdout_redaction=stdout_redaction,
                    stderr_redaction=stderr_redaction,
                    exit_mapping=None,
                    completed_event_payload=None,
                    cancelled_via_registry=cancelled_via_registry,
                    credential_canary_hit_kinds=merged_hits,
                )
            raise exc

        launcher_result: LauncherResult = launch_task.result()
        stdout_redaction, _stdout_hits = _read_and_redact(
            Path(workdir.output_file),
            max_bytes=self.registry.get(request.agent_name).max_stdout_bytes,
        )
        stderr_redaction, _stderr_hits = _read_and_redact(
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

        # SP-PHASE0 gate C defense-in-depth: success path で launcher の canary
        # scan は既に先に CREDENTIAL_EXFILTRATION を raise しているため通常
        # unreachable だが、drain helper の scan が hit したら hit-kind を surface
        # する (二重防御で漏れを残さない)。
        success_hits = tuple(sorted(set(_stdout_hits) | set(_stderr_hits)))
        return CliInvocationOutcome(
            workdir=workdir,
            launcher_result=launcher_result,
            launcher_error_reason=None,
            stdout_redaction=stdout_redaction,
            stderr_redaction=stderr_redaction,
            exit_mapping=exit_mapping,
            completed_event_payload=completed_event_payload,
            cancelled_via_registry=cancelled_via_registry,
            credential_canary_hit_kinds=success_hits,
        )


_EMPTY_WORKDIR = PerRunWorkdir(
    workdir="",
    prompt_file="",
    output_file="",
    stream_file="",
    launch_id="",
)


# SP-PHASE0 gate C (Codex adversarial HIGH 2): credential exfiltration 検出時の
# fail-closed placeholder。raw artifact を再読込・再 redact せず固定文字列のみ emit
# する (narrower redactor で raw credential が survive する経路を物理削除)。
_CREDENTIAL_WITHHELD_TEXT = "[withheld: credential_exfiltration]"


def _withheld_redaction() -> RedactionResult:
    """credential exfiltration 時の固定 placeholder ``RedactionResult``。

    raw artifact 内容を一切含まず、``[withheld: credential_exfiltration]`` の
    content + その SHA-256 hash のみ。caller (AgentRuntime) が artifact /
    AgentRunEvent に永続化しても raw credential は出ない (AC-HARD-02)。
    """

    import hashlib  # noqa: PLC0415

    digest = hashlib.sha256(_CREDENTIAL_WITHHELD_TEXT.encode("utf-8")).hexdigest()
    return RedactionResult(
        redacted_text=_CREDENTIAL_WITHHELD_TEXT,
        redacted_content_hash=digest,
        raw_bytes_length=0,
        truncated=False,
        hits=(),
        prohibited_key_hits=(),
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
) -> tuple[RedactionResult, RedactionResult, tuple[str, ...]]:
    """workdir の output / stream を read + redaction する.

    SP-PHASE0 gate C (Codex adversarial HIGH sibling-path fix, uniform
    defense-in-depth): each drained stream is **first** scanned for credential
    exfiltration with the full credential canary (JWT / codex_refresh_token /
    anthropic OAuth / JSON key-name / path-echo + broad scanner). On a hit the
    stream is returned as a ``[withheld: credential_exfiltration]`` placeholder
    instead of running ``redact_stream`` — whose narrower ``_RAW_SECRET_PATTERNS``
    would let the raw credential survive into ``redacted_text`` + ``content_hash``
    → persisted by the caller (AC-HARD-02). This closes **all** drain paths
    (cancel-during-launch / cancelled-before-launch / any future caller), not just
    the launcher's own post-completion scan.

    Returns ``(stdout_redaction, stderr_redaction, credential_canary_hit_kinds)``.
    """

    # entry は AgentRegistryEntry だが循環 import 防止のため object 受け取り
    max_stdout = int(getattr(entry, "max_stdout_bytes", 1024 * 1024))
    max_stderr = int(getattr(entry, "max_stderr_bytes", 512 * 1024))
    hit_kinds: set[str] = set()
    if workdir.output_file:
        stdout_redaction, out_hits = _read_and_redact(
            Path(workdir.output_file), max_bytes=max_stdout
        )
        hit_kinds.update(out_hits)
    else:
        stdout_redaction = redact_stream(b"", max_bytes=max_stdout)
    if workdir.stream_file:
        stderr_redaction, err_hits = _read_and_redact(
            Path(workdir.stream_file), max_bytes=max_stderr
        )
        hit_kinds.update(err_hits)
    else:
        stderr_redaction = redact_stream(b"", max_bytes=max_stderr)
    return stdout_redaction, stderr_redaction, tuple(sorted(hit_kinds))


def _read_and_redact(
    path: Path, *, max_bytes: int
) -> tuple[RedactionResult, tuple[str, ...]]:
    """File から bytes を読み credential canary scan → redaction pipeline に通す。

    O_RDONLY|O_NOFOLLOW で open し、parent-swap race を狭める。max_bytes
    超過は redaction pipeline が truncate を記録。

    SP-PHASE0 gate C (uniform fail-closed): raw bytes を decode (errors="replace"
    で raw 非再放出) して credential canary scan を先に通す。hit があれば narrow
    ``redact_stream`` を呼ばず ``_withheld_redaction()`` placeholder を返す (raw
    credential が redacted_text / content_hash に残る経路を物理削除)。戻り値の
    hit_kinds は raw 値非含 (pattern_kind のみ)。
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
    # decode は raw bytes を保持しない (errors="replace")。canary scan は redaction
    # より前に行い、hit があれば narrow redact 結果を返さない。
    decoded = raw.decode("utf-8", errors="replace")
    canary = scan_for_credential_exfiltration(decoded)
    if canary.hit:
        hit_kinds = tuple(sorted({h.pattern_kind for h in canary.hits}))
        return _withheld_redaction(), hit_kinds
    return redact_stream(raw, max_bytes=max_bytes), ()


__all__ = [
    "CliInvocationOrchestrator",
    "CliInvocationOutcome",
    "CliInvocationRequest",
]
