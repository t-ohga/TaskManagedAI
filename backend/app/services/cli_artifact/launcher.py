"""Sprint 6 BL-0065: subprocess-based CLI agent launcher.

ADR-00003 §A boundary (CliArtifactAdapter):
- Codex / Claude / 任意 CLI を **subprocess** で実行
- ``shell=False`` 固定、registry の ``argv_template`` だけが allowed argv 構築経路
- ENV は scrubbed (registry ``env_passthrough`` allowlist + forbidden secret denylist)
- stdout / stderr は **必ずバイト数 cap** を持つ (DoS 防御)
- timeout / cancel は ``asyncio.wait_for`` + SIGTERM → SIGKILL escalation
- 結果は artifact_kind=cli_input / cli_stdout / cli_stderr / cli_exit /
  cli_result_summary で artifact store に置く (本 module は launcher のみ、
  artifact 永続化は呼び元 service が担当)

Server-owned-boundary §1 invariant:
- caller (API endpoint / service layer) は ``LauncherRunRequest`` に raw secret
  を入れられない (Pydantic Field validator + assert_no_raw_secret recursive scan)
- ``LauncherResult.payload_data_class`` は server 側 (input artifact metadata)
  から resolve、caller-supplied 禁止
- ``content_hash`` は launcher が SHA-256 で算出 (caller 入力ではない)
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import os
import signal
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from stat import S_ISREG
from typing import IO

from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.cli_artifact.credential_canary import (
    CredentialCanaryHit,
    CredentialCanaryResult,
    scan_streams_for_credential_exfiltration,
)
from backend.app.services.cli_artifact.registry import (
    AgentRegistryEntry,
    CliAgentRegistry,
)

# AC-HARD-05 forbidden path enforcement at launcher boundary
# (rules/ai-output-boundary.md §86 + Codex SP6B1 R2 F-SP6B1-R2-001).
# Even when a path lives inside the registry cwd_allowlist, these substrings
# are denied as a defense-in-depth net. Service layer (Sprint 6 batch 2) will
# additionally route writes into a server-owned per-run artifact workdir.
_FORBIDDEN_PATH_FRAGMENTS: tuple[str, ...] = (
    "/.git/",
    "/.env",
    "/secrets/",
    "/migrations/",
    "/.github/workflows/",
    "/.claude/local/",
    # Codex SP6B1 R3 F-SP6B1-R3-002 adopt: Codex / Claude harness 改ざん経路を
    # deny する。worktree base 配下の `.claude/worktrees/` 自身は cwd 検査で
    # 通過するが、prompt/output/stream に harness file 自体を指定する経路を
    # 物理的に塞ぐ。
    "/.codex/",
    "/.claude/settings.json",
    "/.claude/settings.local.json",
    "/.claude/CLAUDE.md",
    "/.claude/hooks/",
    "/.claude/agents/",
    "/.claude/skills/",
    "/.claude/rules/",
    "/.claude/reference/",
    "/.claude/commands/",
    # Host secret stores.
    "/.ssh/",
    "/.aws/",
    "/.kube/",
)

# Bounded grace for the stdout/stderr drainers after the subprocess has been
# terminated. Without this, a child that inherits and never closes a pipe fd
# would hang the launcher indefinitely (Codex SP6B1 R2 F-SP6B1-R2-003).
_DRAIN_AFTER_TERMINATE_GRACE = 5.0

_SIGTERM_GRACE_SECONDS = 5.0


class LauncherDenyReason(StrEnum):
    """Reasons the launcher refuses to spawn a subprocess.

    These map to ``runner_blocked`` AgentRunEvent ``reason_code`` values
    (rules/agentrun-state-machine §6 + DD-04 §runner deny taxonomy)."""

    AGENT_NOT_IN_REGISTRY = "agent_not_in_registry"
    BINARY_NOT_FOUND = "binary_not_found"
    BINARY_NOT_ABSOLUTE = "binary_not_absolute"
    PROMPT_FILE_NOT_READABLE = "prompt_file_not_readable"
    OUTPUT_FILE_NOT_WRITABLE = "output_file_not_writable"
    CWD_OUTSIDE_ALLOWLIST = "cwd_outside_allowlist"
    PATH_OUTSIDE_CWD = "path_outside_cwd"
    PATH_IS_SYMLINK = "path_is_symlink"
    PATH_FORBIDDEN = "path_forbidden"
    REGISTRY_INVALID = "registry_invalid"
    # SP-PHASE0 gate C (ADR-00058 §exit must_ship): host-ambient CLI が credential
    # file (~/.codex/auth.json 等) を stdout / stderr / output / stream artifact へ
    # exfiltrate した (prompt-injection で `cat <credential>` 等を実行した) ことを
    # 出力 canary scan が検出した場合の Hard Gate failure。raw 値は残さず hit 種別
    # のみ audit する (rules/secretbroker-boundary.md §11)。
    CREDENTIAL_EXFILTRATION = "credential_exfiltration"


class LauncherError(Exception):
    """Launcher refused to spawn the subprocess, or a post-launch Hard Gate
    failure (e.g. credential exfiltration detected in captured output).

    ``canary_hits`` carries the credential canary hit metadata (hit 種別 +
    match count のみ、raw 値非含) for ``CREDENTIAL_EXFILTRATION`` so the caller
    can record it in the audit event without re-scanning.
    """

    def __init__(
        self,
        reason: LauncherDenyReason,
        message: str,
        *,
        canary_hits: tuple[CredentialCanaryHit, ...] = (),
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.canary_hits = canary_hits


@dataclass(frozen=True, slots=True)
class LauncherRunRequest:
    """Caller-built launcher request (kept narrow for security review).

    server-owned-boundary §1 invariant:
    - ``payload_data_class`` は本 signature に **存在しない** (Codex SP6B1 R1
      F-SP6B1-001 採用: caller-supplied data class 経路を物理削除、data class
      boundary は service layer wrapper の責任、batch 2 で artifact_ref →
      data class resolve を実装する)。
    - ``content_hash`` は launcher が SHA-256 で算出 (caller 入力ではない)。
    - ``prompt_file`` / ``output_file`` / ``stream_file`` / ``cwd`` は caller
      入力だが、launcher が registry の ``cwd_allowlist`` 配下に containment
      を強制 (Path.resolve() + base-dir prefix match + symlink reject)。
    """

    agent_name: str
    prompt_file: str  # absolute path, must be inside registry cwd_allowlist
    output_file: str  # absolute path, must be inside registry cwd_allowlist
    stream_file: str  # absolute path, must be inside registry cwd_allowlist
    cwd: str  # subprocess cwd, must be inside registry cwd_allowlist


@dataclass(frozen=True, slots=True)
class _ResolvedLauncherPaths:
    """Canonical paths derived from caller request (validation result).

    Codex SP6B1 R2 F-SP6B1-R2-002: subprocess argv/cwd/stdin MUST use these
    canonical strings, not the raw caller-supplied ``request.*`` fields, so a
    TOCTOU swap of the path between validation and spawn cannot redirect IO.
    """

    cwd: str
    prompt_file: str
    output_file: str
    stream_file: str


@dataclass(frozen=True, slots=True)
class LauncherResult:
    """Outcome of a single launcher invocation (used by artifact builder)."""

    agent_name: str
    exit_code: int | None
    timeout_reached: bool
    cancelled: bool
    duration_seconds: float
    stdout_bytes: int
    stderr_bytes: int
    signal: str | None = None


async def launch_cli_agent(
    request: LauncherRunRequest,
    registry: CliAgentRegistry,
) -> LauncherResult:
    """Spawn the registered CLI agent and capture stdout/stderr with caps.

    Raises:
        LauncherError: pre-launch deny (registry / data class / path).
    """

    # 1. agent allowlist check
    try:
        entry = registry.get(request.agent_name)
    except KeyError as exc:
        raise LauncherError(
            LauncherDenyReason.AGENT_NOT_IN_REGISTRY,
            f"agent {request.agent_name!r} not in registry",
        ) from exc

    # 2. cwd allowlist + path containment (server-owned-boundary §1,
    #    AC-HARD-05 forbidden path enforcement at launcher boundary).
    #    Codex SP6B1 R2 F-SP6B1-R2-002: argv/cwd/stdin must consume the
    #    canonical resolved paths, not the raw caller-supplied strings.
    resolved_cwd = _resolve_and_check_containment(
        path=request.cwd,
        allowlist=entry.cwd_allowlist,
        agent_name=entry.name,
        path_kind="cwd",
        symlink_reason=LauncherDenyReason.PATH_IS_SYMLINK,
        outside_reason=LauncherDenyReason.CWD_OUTSIDE_ALLOWLIST,
    )
    resolved_prompt = _resolve_and_check_containment(
        path=request.prompt_file,
        allowlist=(resolved_cwd,),
        agent_name=entry.name,
        path_kind="prompt_file",
        symlink_reason=LauncherDenyReason.PATH_IS_SYMLINK,
        outside_reason=LauncherDenyReason.PATH_OUTSIDE_CWD,
    )
    resolved_output = _resolve_and_check_containment(
        path=request.output_file,
        allowlist=(resolved_cwd,),
        agent_name=entry.name,
        path_kind="output_file",
        symlink_reason=LauncherDenyReason.PATH_IS_SYMLINK,
        outside_reason=LauncherDenyReason.PATH_OUTSIDE_CWD,
    )
    resolved_stream = _resolve_and_check_containment(
        path=request.stream_file,
        allowlist=(resolved_cwd,),
        agent_name=entry.name,
        path_kind="stream_file",
        symlink_reason=LauncherDenyReason.PATH_IS_SYMLINK,
        outside_reason=LauncherDenyReason.PATH_OUTSIDE_CWD,
    )
    resolved_paths = _ResolvedLauncherPaths(
        cwd=resolved_cwd,
        prompt_file=resolved_prompt,
        output_file=resolved_output,
        stream_file=resolved_stream,
    )

    # 3. binary resolution (absolute path required, Codex SP6B1 R2 F-SP6B1-R2-004)
    resolved_binary = _resolve_binary(entry)
    if resolved_binary is None:
        raise LauncherError(
            LauncherDenyReason.BINARY_NOT_FOUND,
            f"agent {entry.name!r} binary not found: {entry.binary_path!r}",
        )

    # 4. argv build with placeholder substitution (uses canonical paths only)
    argv = _build_argv(entry, resolved_paths, resolved_binary)

    # 5. scrubbed ENV
    env = _build_scrubbed_env(entry)
    assert_no_raw_secret(dict(env), path="$cli_launcher.env")

    # 6. stdin source (canonical path only)
    stdin_path: str | None = None
    if entry.stdin_source == "{prompt_file}":
        stdin_path = resolved_paths.prompt_file
    elif entry.stdin_source == "{output_file}":
        stdin_path = resolved_paths.output_file
    elif entry.stdin_source == "{stream_file}":
        stdin_path = resolved_paths.stream_file
    elif entry.stdin_source != "":
        raise LauncherError(
            LauncherDenyReason.REGISTRY_INVALID,
            f"unknown stdin_source placeholder {entry.stdin_source!r}",
        )

    if stdin_path is not None and not os.access(stdin_path, os.R_OK):
        raise LauncherError(
            LauncherDenyReason.PROMPT_FILE_NOT_READABLE,
            f"stdin file is not readable: {stdin_path}",
        )

    # 7. spawn + read with caps (canonical cwd only)
    return await _spawn_with_caps(
        argv=argv,
        env=env,
        cwd=resolved_paths.cwd,
        timeout_seconds=entry.timeout_seconds,
        max_stdout_bytes=entry.max_stdout_bytes,
        max_stderr_bytes=entry.max_stderr_bytes,
        stdin_path=stdin_path,
        agent_name=entry.name,
        # SP-PHASE0 gate C (control 1): output / stream artifact paths are scanned
        # for credential exfiltration alongside captured stdout/stderr. codex
        # writes its real response into output_file (--output-last-message), so
        # a credential echoed there must also be caught.
        output_file=resolved_paths.output_file,
        stream_file=resolved_paths.stream_file,
    )


def _resolve_binary(entry: AgentRegistryEntry) -> str | None:
    """Resolve the binary path.

    Codex SP6B1 R2 F-SP6B1-R2-004: ``binary_path`` MUST be absolute (enforced
    by ``AgentRegistryEntry.__post_init__``). ``shutil.which`` is intentionally
    NOT used here so a PATH-only environment cannot redirect to a different
    binary. ``Path.resolve(strict=True)`` follows symlinks (binaries often
    live behind a symlink, e.g. ``/opt/homebrew/bin/codex`` -> Cellar) but
    refuses to resolve a missing target.
    """

    binary = entry.binary_path
    if not os.path.isabs(binary):
        return None
    try:
        resolved = Path(binary).resolve(strict=True)
    except OSError:
        return None
    return str(resolved) if os.access(resolved, os.X_OK) else None


def _build_argv(
    entry: AgentRegistryEntry,
    resolved_paths: _ResolvedLauncherPaths,
    resolved_binary: str,
) -> list[str]:
    substitutions = {
        "{prompt_file}": resolved_paths.prompt_file,
        "{output_file}": resolved_paths.output_file,
        "{stream_file}": resolved_paths.stream_file,
    }
    argv: list[str] = [resolved_binary]
    for piece in entry.argv_template:
        if piece in substitutions:
            argv.append(substitutions[piece])
        else:
            # piece may NOT contain raw placeholders (registry __post_init__
            # ensures only allowlisted ones can appear); literal strings pass
            # through unchanged.
            argv.append(piece)
    return argv


def _build_scrubbed_env(entry: AgentRegistryEntry) -> dict[str, str]:
    parent = os.environ
    env: dict[str, str] = {}
    for var in entry.env_passthrough:
        # forbidden secrets are blocked at registry-load time, but
        # defense-in-depth: re-check here in case registry was hot-reloaded.
        from backend.app.services.cli_artifact.registry import (
            _FORBIDDEN_ENV_NAMES,  # noqa: PLC0415
        )

        if var in _FORBIDDEN_ENV_NAMES:
            continue
        if var in parent:
            env[var] = parent[var]
    # Always-on minimal env so the subprocess can locate libc / locale data.
    env.setdefault("PATH", "/usr/bin:/bin")
    env.setdefault("LANG", "C.UTF-8")
    # SP-PHASE0 gate C (control 2, defense-in-depth, ADR-00058 §exit must_ship):
    # per-agent 最小 HOME override + credential home env。host-ambient CLI が
    # prompt-injected な ``cat ~/.ssh/id_rsa`` / ``cat ~/.aws/...`` 等で **他 secret**
    # を読む blast radius を制限する。HOME を agent 固有最小 dir へ振り、その配下に
    # 他 secret を同居させないことで、相対 ``~`` 参照の他 secret 読取を構造的に空に
    # する。agent 自身の credential は ``credential_home_env`` (codex→CODEX_HOME) で
    # 別 dir を明示供給するため読取は維持される。
    #
    # 最小 HOME は ``env_passthrough`` で渡る parent ``HOME`` を **上書き** する
    # (set 順は本ブロックが最後なので override が効く)。未設定 (後方互換) の場合は
    # 既存挙動 (parent HOME passthrough) のまま。
    if entry.minimal_home_dir is not None:
        env["HOME"] = entry.minimal_home_dir
    if entry.credential_home_env is not None and entry.credential_home_dir is not None:
        env[entry.credential_home_env] = entry.credential_home_dir
    # Hint downstream CLI tools that we are running in CI-like mode.
    env["TASKMANAGEDAI_CLI_LAUNCHER"] = entry.name
    return env


def _resolve_and_check_containment(
    *,
    path: str,
    allowlist: tuple[str, ...],
    agent_name: str,
    path_kind: str,
    symlink_reason: LauncherDenyReason,
    outside_reason: LauncherDenyReason,
) -> str:
    """Resolve ``path`` and confirm it lives inside one of the allowlisted
    base directories. Reject symlinks (any component) to prevent escape via
    crafted symlink trees.

    Returns the resolved absolute path string.
    """

    if not path:
        raise LauncherError(
            outside_reason,
            f"agent {agent_name!r}: {path_kind} must be a non-empty path",
        )
    candidate = Path(path)
    # Reject the path itself being a symlink, and any parent in the chain.
    probe: Path | None = candidate
    while probe is not None and str(probe) not in ("/", ""):
        if probe.is_symlink():
            raise LauncherError(
                symlink_reason,
                f"agent {agent_name!r}: {path_kind} path component is a "
                f"symlink ({probe!s}), refusing to follow",
            )
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise LauncherError(
            outside_reason,
            f"agent {agent_name!r}: {path_kind} could not be resolved: {exc}",
        ) from exc
    resolved_str = str(resolved)
    # AC-HARD-05 forbidden path enforcement at the launcher boundary
    # (Codex SP6B1 R2 F-SP6B1-R2-001 + R3 F-SP6B1-R3-002).
    if path_kind != "cwd":
        for fragment in _FORBIDDEN_PATH_FRAGMENTS:
            if fragment in resolved_str or resolved_str.endswith(
                fragment.rstrip("/")
            ):
                raise LauncherError(
                    LauncherDenyReason.PATH_FORBIDDEN,
                    f"agent {agent_name!r}: {path_kind} {resolved_str!r} "
                    f"matches forbidden path fragment {fragment!r}",
                )
    # Codex SP6B1 R3 F-SP6B1-R3-003 partial adopt: output/stream の TOCTOU
    # race window を狭めるため、parent directory が backend process と同じ
    # uid 所有である (= 他ユーザーが parent に書込めない) ことを確認する。
    # 完全な解決 (server-owned per-run directory + fd-based open) は Sprint 6
    # batch 2 で server-owned artifact workdir として実装する。
    if path_kind in ("output_file", "stream_file"):
        parent = Path(resolved_str).parent
        try:
            pstat = parent.lstat()
        except OSError as exc:
            raise LauncherError(
                outside_reason,
                f"agent {agent_name!r}: {path_kind} parent {parent!s} "
                f"could not be stat-ed: {exc}",
            ) from exc
        if pstat.st_uid != os.getuid():
            raise LauncherError(
                outside_reason,
                f"agent {agent_name!r}: {path_kind} parent {parent!s} is "
                f"not owned by the backend uid ({pstat.st_uid} != "
                f"{os.getuid()}); refusing to write through it",
            )
    for base in allowlist:
        base_resolved = str(Path(base).resolve(strict=False))
        # base-dir prefix match with trailing separator to avoid
        # ``/foo/bar`` matching ``/foo/barbaz``.
        if (
            resolved_str == base_resolved
            or resolved_str.startswith(base_resolved + os.sep)
        ):
            return resolved_str
    raise LauncherError(
        outside_reason,
        f"agent {agent_name!r}: {path_kind} {resolved_str!r} is outside "
        f"allowlist {sorted(allowlist)!r}",
    )


async def _spawn_with_caps(
    *,
    argv: list[str],
    env: dict[str, str],
    cwd: str,
    timeout_seconds: int,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
    stdin_path: str | None,
    agent_name: str,
    output_file: str | None = None,
    stream_file: str | None = None,
) -> LauncherResult:
    loop = asyncio.get_running_loop()
    start = loop.time()

    stdin_handle: IO[bytes] | None = None
    if stdin_path is not None:
        # Codex SP6B1 R2 F-SP6B1-R2-002: open the stdin file via fd to defeat
        # the post-validation symlink swap; O_NOFOLLOW refuses to follow a
        # final-component symlink (best effort across POSIX flavors).
        flags = os.O_RDONLY
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if nofollow:
            flags |= nofollow
        try:
            fd = os.open(stdin_path, flags)
        except OSError as exc:
            elloop = getattr(errno, "ELOOP", None)
            enotdir = getattr(errno, "ENOTDIR", None)
            raise LauncherError(
                LauncherDenyReason.PATH_IS_SYMLINK
                if exc.errno in {elloop, enotdir}
                else LauncherDenyReason.PROMPT_FILE_NOT_READABLE,
                f"agent {agent_name!r}: stdin open failed: {exc}",
            ) from exc
        stinfo = os.fstat(fd)
        if not S_ISREG(stinfo.st_mode):
            os.close(fd)
            raise LauncherError(
                LauncherDenyReason.PROMPT_FILE_NOT_READABLE,
                f"agent {agent_name!r}: stdin is not a regular file "
                f"({stdin_path!r})",
            )
        stdin_handle = os.fdopen(fd, "rb")

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=stdin_handle if stdin_handle is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            # Codex SP6B1 R2 F-SP6B1-R2-003: isolate the subprocess in a new
            # session/process group so timeout/cancel can SIGTERM the whole
            # tree (including children the CLI agent may fork).
            start_new_session=True,
        )
    finally:
        if stdin_handle is not None:
            try:
                stdin_handle.close()
            except OSError:
                pass

    timeout_reached = False
    cancelled = False
    stdout_bytes_read = 0
    stderr_bytes_read = 0
    stdout_captured = b""
    stderr_captured = b""
    signal_name: str | None = None

    async def _drain(
        stream: asyncio.StreamReader | None,
        cap: int,
    ) -> tuple[int, bytes]:
        """Drain ``stream`` up to ``cap`` bytes.

        Returns ``(byte_count, captured_bytes)``. SP-PHASE0 gate C: the captured
        bytes (bounded by ``cap``, so no new DoS surface beyond the existing
        byte cap) are retained so the post-completion credential canary scan can
        inspect the actual stdout/stderr content. Bytes beyond ``cap`` are
        discarded but the pipe is still drained so the subprocess never blocks.
        """

        if stream is None:
            return 0, b""
        total = 0
        captured = bytearray()
        while True:
            chunk = await stream.read(64 * 1024)
            if not chunk:
                break
            remaining = cap - total
            if remaining <= 0:
                # We have already saturated the cap; keep draining so the
                # subprocess never blocks on a full pipe, but discard data.
                continue
            keep = min(len(chunk), remaining)
            total += keep
            captured.extend(chunk[:keep])
        return total, bytes(captured)

    stdout_task = asyncio.create_task(_drain(proc.stdout, max_stdout_bytes))
    stderr_task = asyncio.create_task(_drain(proc.stderr, max_stderr_bytes))

    exit_code: int | None
    try:
        exit_code = await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
    except TimeoutError:
        timeout_reached = True
        exit_code = await _terminate_with_grace(proc)
    except asyncio.CancelledError:
        cancelled = True
        exit_code = await _terminate_with_grace(proc)
        raise
    finally:
        # Bounded drainer await: a leaked pipe fd in a grandchild must not
        # hang the launcher (Codex SP6B1 R2 F-SP6B1-R2-003).
        for task in (stdout_task, stderr_task):
            try:
                await asyncio.wait_for(task, timeout=_DRAIN_AFTER_TERMINATE_GRACE)
            except TimeoutError:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, OSError):
                    pass
        if stdout_task.done() and not stdout_task.cancelled():
            stdout_bytes_read, stdout_captured = stdout_task.result()
        if stderr_task.done() and not stderr_task.cancelled():
            stderr_bytes_read, stderr_captured = stderr_task.result()

    if exit_code is not None and exit_code < 0:
        # POSIX convention: -N means killed by signal N.
        try:
            signal_name = signal.Signals(-exit_code).name
        except (ValueError, ImportError):
            signal_name = f"signal_{-exit_code}"

    # SP-PHASE0 gate C (control 1, ADR-00058 §exit must_ship): credential
    # exfiltration canary scan. After capturing stdout / stderr (+ output /
    # stream artifact), scan for credential / secret token patterns. A hit means
    # the (untrusted) prompt drove the CLI to exfiltrate a credential (e.g. via a
    # prompt-injected ``cat ~/.codex/auth.json``). This is a Hard Gate failure:
    # raise ``CREDENTIAL_EXFILTRATION`` so the result is treated as a deny, the
    # raw output is NOT returned (fail-closed), and only the hit 種別 is surfaced
    # for audit (raw 値非含、rules/secretbroker-boundary.md §11 / AC-HARD-02).
    canary = _scan_outputs_for_exfiltration(
        stdout_captured=stdout_captured,
        stderr_captured=stderr_captured,
        output_file=output_file,
        stream_file=stream_file,
        max_stdout_bytes=max_stdout_bytes,
        max_stderr_bytes=max_stderr_bytes,
    )
    if canary.hit:
        hit_kinds = sorted({h.pattern_kind for h in canary.hits})
        raise LauncherError(
            LauncherDenyReason.CREDENTIAL_EXFILTRATION,
            f"agent {agent_name!r}: credential exfiltration detected in CLI "
            f"output (hit kinds: {hit_kinds}); raw output withheld",
            canary_hits=canary.hits,
        )

    duration = loop.time() - start
    return LauncherResult(
        agent_name=agent_name,
        exit_code=exit_code,
        timeout_reached=timeout_reached,
        cancelled=cancelled,
        duration_seconds=duration,
        stdout_bytes=stdout_bytes_read,
        stderr_bytes=stderr_bytes_read,
        signal=signal_name,
    )


def _scan_outputs_for_exfiltration(
    *,
    stdout_captured: bytes,
    stderr_captured: bytes,
    output_file: str | None,
    stream_file: str | None,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> CredentialCanaryResult:
    """SP-PHASE0 gate C (control 1): scan captured streams + artifacts.

    Decodes the captured stdout / stderr bytes (errors="replace" so raw bytes
    are never re-emitted) and reads the output / stream artifact files (bounded
    by the byte caps, O_NOFOLLOW to avoid a parent-swap symlink), then runs the
    credential canary scan over all of them. Returns a hit-only result (raw 値
    非含).
    """

    streams: list[str] = [
        stdout_captured.decode("utf-8", errors="replace"),
        stderr_captured.decode("utf-8", errors="replace"),
    ]
    if output_file is not None:
        streams.append(_read_capped_text(output_file, max_bytes=max_stdout_bytes))
    if stream_file is not None:
        streams.append(_read_capped_text(stream_file, max_bytes=max_stderr_bytes))
    return scan_streams_for_credential_exfiltration(*streams)


def _read_capped_text(path: str, *, max_bytes: int) -> str:
    """Read at most ``max_bytes`` from ``path`` and decode (errors="replace").

    O_NOFOLLOW refuses a final-component symlink swap. Read failures yield an
    empty string (fail-open on read is acceptable here because the captured
    stdout/stderr streams are the primary canary surface; the artifact files are
    a secondary cross-check). Bytes are never returned raw.
    """

    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    try:
        fd = os.open(path, flags)
    except OSError:
        return ""
    try:
        with os.fdopen(fd, "rb") as fp:
            raw = fp.read(max_bytes)
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


async def _terminate_with_grace(
    proc: asyncio.subprocess.Process,
) -> int | None:
    """SIGTERM (process group) → grace → SIGKILL (process group) escalation.

    Codex SP6B1 R2 F-SP6B1-R2-003: signal the whole process group started by
    ``start_new_session=True`` so descendants forked by the CLI agent are
    reaped instead of remaining as orphans inheriting our stdout/stderr pipes.
    """

    if proc.returncode is not None:
        return proc.returncode
    pgid: int | None
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
        return proc.returncode
    try:
        return await asyncio.wait_for(
            proc.wait(),
            timeout=_SIGTERM_GRACE_SECONDS,
        )
    except TimeoutError:
        try:
            if pgid is not None and hasattr(os, "killpg"):
                os.killpg(pgid, signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            return proc.returncode
        try:
            return await asyncio.wait_for(proc.wait(), timeout=1.0)
        except TimeoutError:
            return proc.returncode


def compute_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "LauncherDenyReason",
    "LauncherError",
    "LauncherResult",
    "LauncherRunRequest",
    "compute_text_hash",
    "launch_cli_agent",
]
