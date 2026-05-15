# ruff: noqa: S108, ASYNC240
"""Sprint 7 BL-0071: RunnerAdapter interface and mock runner tests."""

from __future__ import annotations

import asyncio
import dataclasses
import os
import stat
import uuid
from pathlib import Path

import pytest

from backend.app.services.runner.runner_adapter import (
    MockRunnerAdapter,
    RunnerAdapter,
    RunnerCancelToken,
    RunnerCommandRequest,
    RunnerCommandResult,
    RunnerExecutionContext,
    RunnerWorkspace,
)

POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix",
    reason="/bin/sh を使う subprocess test は POSIX 環境だけで実行する",
)


def _secret_env_values() -> dict[str, str]:
    return {
        "OPENAI_API_KEY": "sk-" + ("A" * 40),
        "ANTHROPIC_API_KEY": "sk-ant-" + ("B" * 40),
        "GITHUB_TOKEN": "ghs_" + ("C" * 40),
        "GH_TOKEN": "ghp_" + ("D" * 40),
        "GITHUB_APP_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----dummy",
        "TAILSCALE_AUTHKEY": "tskey-" + ("e" * 20) + "-" + ("f" * 20),
        "SOPS_AGE_KEY": "AGE-SECRET-KEY-1" + ("G" * 60),
        "AGE_SECRET_KEY": "AGE-SECRET-KEY-1" + ("H" * 60),
        "AWS_SECRET_ACCESS_KEY": "aws-secret-" + ("I" * 32),
        "AWS_SESSION_TOKEN": "aws-session-" + ("J" * 32),
        "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/not-real-service-account.json",
        "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_" + ("K" * 32),
        "DATABASE_URL": "postgresql://user:dummy-password@localhost:5432/app",
        "REDIS_URL": "redis://:dummy-password@localhost:6379/0",
    }


async def _prepared_workspace(tmp_path: Path, run_id: str = "run-001") -> tuple[MockRunnerAdapter, RunnerWorkspace]:
    adapter = MockRunnerAdapter(base_dir=str(tmp_path))
    workspace = await adapter.prepare_workspace(run_id)
    return adapter, workspace


def test_runner_adapter_is_abc() -> None:
    """RunnerAdapter は抽象 interface であり直接 instantiate できない。"""

    with pytest.raises(TypeError, match="abstract"):
        RunnerAdapter()


def test_runner_adapter_has_4_methods() -> None:
    """RunnerAdapter は runner lifecycle の 4 method を公開する。"""

    expected = frozenset(
        {
            "prepare_workspace",
            "run_command",
            "collect_artifacts",
            "cleanup",
        }
    )

    assert RunnerAdapter.__abstractmethods__ == expected
    for method_name in expected:
        assert callable(getattr(RunnerAdapter, method_name))


@pytest.mark.asyncio
async def test_prepare_workspace_creates_owner_only_dir(tmp_path: Path) -> None:
    """workspace directory は mode 0700 かつ current uid owner で作る。"""

    if not hasattr(os, "getuid"):
        pytest.skip("uid check は POSIX 環境だけで実行する")

    _adapter, workspace = await _prepared_workspace(tmp_path)
    st = os.stat(workspace.workdir)

    assert stat.S_IMODE(st.st_mode) == 0o700
    assert st.st_uid == os.getuid()


@pytest.mark.asyncio
async def test_prepare_workspace_generates_uuid_workspace_id(tmp_path: Path) -> None:
    """workspace_id は server-side 生成 UUID hex とする。"""

    _adapter, workspace = await _prepared_workspace(tmp_path)
    parsed = uuid.UUID(hex=workspace.workspace_id)

    assert parsed.hex == workspace.workspace_id
    assert len(workspace.workspace_id) == 32


@pytest.mark.asyncio
async def test_prepare_workspace_workdir_includes_run_id(tmp_path: Path) -> None:
    """workdir 名には run_id を含め、run 単位で追跡できるようにする。"""

    run_id = "agent-run-abc"
    _adapter, workspace = await _prepared_workspace(tmp_path, run_id=run_id)

    assert workspace.run_id == run_id
    assert run_id in Path(workspace.workdir).name


@pytest.mark.asyncio
async def test_run_command_executes_argv(tmp_path: Path) -> None:
    """run_command は shell string ではなく argv を subprocess として実行する。"""

    adapter, workspace = await _prepared_workspace(tmp_path)
    # Codex SP7 R2 F-001 adopt: `python -c` inline exec が block されるため
    # `/bin/echo hello` で同等の test を実施
    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/echo", "hello"),
            cwd=workspace.workdir,
        ),
        RunnerExecutionContext.p0_default(),
    )

    assert result.exit_code == 0
    assert result.stdout_bytes >= len("hello\n")
    assert result.stderr_bytes == 0
    assert result.timeout_reached is False
    assert result.cancelled is False


@pytest.mark.asyncio
async def test_run_command_rejects_empty_argv(tmp_path: Path) -> None:
    """空 argv は caller bug として ValueError で拒否する。"""

    adapter, workspace = await _prepared_workspace(tmp_path)

    with pytest.raises(ValueError, match="argv"):
        await adapter.run_command(
            workspace,
            RunnerCommandRequest(argv=(), cwd=workspace.workdir),
            RunnerExecutionContext.p0_default(),
        )


@pytest.mark.asyncio
async def test_run_command_rejects_nonexistent_cwd_inside_workspace(tmp_path: Path) -> None:
    """Codex SP7 R3 F-SP7-R3-001 adopt: workspace 配下だが存在しない cwd は
    redacted ValueError で reject (raw cwd 非露出)。"""
    adapter, workspace = await _prepared_workspace(tmp_path)
    nonexistent = Path(workspace.workdir) / "does-not-exist"

    with pytest.raises(ValueError, match="cwd_not_directory") as excinfo:
        await adapter.run_command(
            workspace,
            RunnerCommandRequest(
                argv=("/bin/echo", "ok"),
                cwd=str(nonexistent),
            ),
            RunnerExecutionContext.p0_default(),
        )
    msg = str(excinfo.value)
    assert str(nonexistent) not in msg
    assert workspace.workspace_id in msg
    assert "cwd_hash=" in msg


@pytest.mark.asyncio
async def test_run_command_exception_chain_redaction(tmp_path: Path) -> None:
    """Codex SP7 R4 F-SP7-R4-001 adopt: exception __cause__ も raw cwd を漏らさない。

    Codex SP7 R5 F-SP7-R5-001 adopt: `__context__` も None で raw OSError が
    残らない (except ブロック外で raise pattern で完全切断)。
    """
    import traceback as _traceback

    adapter, workspace = await _prepared_workspace(tmp_path)
    nonexistent = Path(workspace.workdir) / "missing-cwd"

    with pytest.raises(ValueError) as excinfo:
        await adapter.run_command(
            workspace,
            RunnerCommandRequest(
                argv=("/bin/echo", "ok"),
                cwd=str(nonexistent),
            ),
            RunnerExecutionContext.p0_default(),
        )

    # exception chain 完全切断 (__cause__ + __context__ どちらも None)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None, (
        f"__context__ not severed; remaining = {excinfo.value.__context__!r}"
    )
    formatted = "".join(
        _traceback.format_exception(
            type(excinfo.value), excinfo.value, excinfo.tb
        )
    )
    assert str(nonexistent) not in formatted


@pytest.mark.asyncio
async def test_run_command_subprocess_exec_failed_redaction(tmp_path: Path) -> None:
    """Codex SP7 R5 F-SP7-R5-001 adopt: subprocess_exec_failed の OSError catch
    経路で __cause__ + __context__ が両方 None。

    実在しない /usr/bin/this-binary-does-not-exist を実行して OSError 発生、
    redacted ValueError + chain 完全切断 verify。
    """
    adapter, workspace = await _prepared_workspace(tmp_path)

    # 実在しない command を workspace 内に絶対パスで指定
    nonexistent_binary = Path(workspace.workdir) / "no-such-binary"

    with pytest.raises(ValueError, match="subprocess_exec_failed") as excinfo:
        await adapter.run_command(
            workspace,
            RunnerCommandRequest(
                argv=(str(nonexistent_binary), "arg1"),
                cwd=workspace.workdir,
            ),
            RunnerExecutionContext.p0_default(),
        )

    # __cause__ + __context__ 両方切断
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None, (
        f"__context__ not severed; remaining = {excinfo.value.__context__!r}"
    )
    msg = str(excinfo.value)
    # raw absolute path 非露出 (basename のみ含む)
    assert str(nonexistent_binary) not in msg
    assert workspace.workspace_id in msg
    assert "argv_basename=no-such-binary" in msg
    assert "argv_hash=" in msg


@pytest.mark.asyncio
async def test_run_command_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    """workspace prefix 偽装を含む outside cwd を containment check で拒否する。

    Codex SP7 R2 F-SP7-R2-001 adopt: exception message に raw cwd / resolved
    path は含まれず、`workspace_id=<hex>` + `cwd_hash=<16-char-sha256>` のみ。
    """

    adapter, workspace = await _prepared_workspace(tmp_path)
    outside = Path(workspace.workdir + "-escape")
    outside.mkdir()

    with pytest.raises(ValueError, match="cwd_outside_workspace") as excinfo:
        await adapter.run_command(
            workspace,
            RunnerCommandRequest(
                argv=("/bin/echo", "should-not-run"),
                cwd=str(outside),
            ),
            RunnerExecutionContext.p0_default(),
        )
    # raw cwd 非露出 invariant verify
    msg = str(excinfo.value)
    assert str(outside) not in msg, f"raw cwd leaked in exception: {msg!r}"
    assert workspace.workspace_id in msg
    assert "cwd_hash=" in msg


@pytest.mark.asyncio
async def test_run_command_timeout(tmp_path: Path) -> None:
    """wall_clock_seconds (resource_policy) を超えた process は terminate され
    timeout flag を返す。

    Codex R1 F-003 adopt: timeout source は resource_policy.wall_clock_seconds
    に一本化。RunnerCommandRequest.timeout_seconds は signature 削除済。
    """
    import dataclasses

    from backend.app.services.runner.resource_cap import ResourcePolicy

    adapter, workspace = await _prepared_workspace(tmp_path)
    short_policy = dataclasses.replace(
        ResourcePolicy.from_p0_defaults(),
        wall_clock_seconds=0.2,
    )
    short_context = dataclasses.replace(
        RunnerExecutionContext.p0_default(),
        resource_policy=short_policy,
    )
    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/sleep", "10"),
            cwd=workspace.workdir,
        ),
        short_context,
    )

    assert result.timeout_reached is True
    assert result.cancelled is False
    assert result.duration_seconds < 5


@pytest.mark.asyncio
async def test_run_command_cancel_token(tmp_path: Path) -> None:
    """cancel_token が cancelled の場合は result.cancelled=True、process group は
    kill される。

    Codex SP7 audit F-SP7-005 adopt: pre-cancelled token を渡すと、cancel watcher
    が即 detect して process group を SIGTERM、result.exit_code は -SIGTERM=-15
    か kill されずに 0 のいずれか (timing-dependent)。**cancelled flag 必須**。
    """

    adapter, workspace = await _prepared_workspace(tmp_path)
    cancel_token = RunnerCancelToken()
    cancel_token.cancel()

    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/echo", "ok"),
            cwd=workspace.workdir,
        ),
        RunnerExecutionContext.p0_default(),
        cancel_token=cancel_token,
    )

    # cancelled flag 必須
    assert result.cancelled is True
    # exit_code は 0 (process が完了してから cancel) または -15 (SIGTERM) / None (immediate kill)
    assert result.exit_code in {0, -15, None}


@POSIX_ONLY
@pytest.mark.asyncio
async def test_run_command_mid_run_cancel_kills_long_process(tmp_path: Path) -> None:
    """Codex SP7 audit F-SP7-005 adopt: mid-run cancel が長時間 process を kill。

    cancel_token を実行中に cancel すると、watcher が detect して process group
    SIGTERM 経路に入り、timeout を待たずに process が終了する。
    """
    adapter, workspace = await _prepared_workspace(tmp_path)
    cancel_token = RunnerCancelToken()

    async def cancel_after(delay: float) -> None:
        await asyncio.sleep(delay)
        cancel_token.cancel()

    # 10s sleep を 0.3s で cancel
    asyncio.create_task(cancel_after(0.3))

    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/sleep", "10"),
            cwd=workspace.workdir,
        ),
        RunnerExecutionContext.p0_default(),
        cancel_token=cancel_token,
    )

    # cancel watcher が動作した証拠: 10s 待たずに終了 (実測 < 5s) + cancelled=True
    assert result.cancelled is True
    assert result.duration_seconds < 5.0


@POSIX_ONLY
@pytest.mark.asyncio
async def test_run_command_env_scrub_removes_openai_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env_allowlist が空なら OPENAI_API_KEY は subprocess に渡さない。"""

    secret = "sk-" + ("A" * 40)
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    adapter, workspace = await _prepared_workspace(tmp_path)
    output = Path(workspace.workdir) / "openai-env.txt"

    # script file 経由に置換
    script = Path(workspace.workdir) / "openai-env.sh"
    script.write_text('printf "%s" "${OPENAI_API_KEY:-}" > openai-env.txt\n')
    script.chmod(0o755)
    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/sh", str(script)),
            cwd=workspace.workdir,
            env_allowlist=frozenset(),
        ),
        RunnerExecutionContext.p0_default(),
    )

    assert result.exit_code == 0
    assert output.read_text(encoding="utf-8") == ""


@POSIX_ONLY
@pytest.mark.asyncio
async def test_run_command_env_scrub_blocks_forbidden_var_even_in_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """forbidden env var は allowlist に入っていても subprocess に渡さない。"""

    secret = "sk-" + ("B" * 40)
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    adapter, workspace = await _prepared_workspace(tmp_path)
    output = Path(workspace.workdir) / "openai-allowlisted.txt"

    # script file 経由に置換
    script = Path(workspace.workdir) / "openai-allowlisted.sh"
    script.write_text(
        'printf "%s" "${OPENAI_API_KEY:-}" > openai-allowlisted.txt\n'
    )
    script.chmod(0o755)
    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/sh", str(script)),
            cwd=workspace.workdir,
            env_allowlist=frozenset({"OPENAI_API_KEY"}),
        ),
        RunnerExecutionContext.p0_default(),
    )

    assert result.exit_code == 0
    assert output.read_text(encoding="utf-8") == ""


@POSIX_ONLY
@pytest.mark.asyncio
async def test_run_command_env_scrub_blocks_known_secret_vars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SecretBroker raw secret 相当の 14 種 key は allowlist にあっても渡さない。"""

    secrets = _secret_env_values()
    for key, value in secrets.items():
        monkeypatch.setenv(key, value)

    adapter, workspace = await _prepared_workspace(tmp_path)
    output = Path(workspace.workdir) / "env-snapshot.txt"
    # Codex SP7 R2 F-001 adopt: `sh -c` inline exec が block されるため、
    # script file 経由に置換 (env を sort して file に write する script)
    script = Path(workspace.workdir) / "env-snapshot.sh"
    script.write_text("env | sort > env-snapshot.txt\n")
    script.chmod(0o755)

    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/sh", str(script)),
            cwd=workspace.workdir,
            env_allowlist=frozenset(secrets),
        ),
        RunnerExecutionContext.p0_default(),
    )

    content = output.read_text(encoding="utf-8")
    assert result.exit_code == 0
    for key, value in secrets.items():
        assert f"{key}=" not in content
        assert value not in content


@POSIX_ONLY
@pytest.mark.asyncio
async def test_run_command_env_allowlist_passes_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATH は allowlist に含めた場合に subprocess へ渡せる。"""

    expected_path = "/custom/bin:/usr/bin:/bin"
    monkeypatch.setenv("PATH", expected_path)
    adapter, workspace = await _prepared_workspace(tmp_path)
    output = Path(workspace.workdir) / "path-env.txt"
    # Codex SP7 R2 F-001 adopt: `sh -c` inline exec が block されるため、
    # script file 経由に置換
    script = Path(workspace.workdir) / "path-env.sh"
    script.write_text('printf "%s" "$PATH" > path-env.txt\n')
    script.chmod(0o755)

    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/sh", str(script)),
            cwd=workspace.workdir,
            env_allowlist=frozenset({"PATH"}),
        ),
        RunnerExecutionContext.p0_default(),
    )

    assert result.exit_code == 0
    assert output.read_text(encoding="utf-8") == expected_path


@pytest.mark.asyncio
async def test_collect_artifacts_returns_files_recursively(tmp_path: Path) -> None:
    """collect_artifacts は workspace 配下の file を再帰的に返す。"""

    adapter, workspace = await _prepared_workspace(tmp_path)
    base = Path(workspace.workdir)
    files = (
        base / "a.txt",
        base / "nested" / "b.txt",
        base / "nested" / "deeper" / "c.txt",
    )
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    artifacts = await adapter.collect_artifacts(workspace)

    assert set(artifacts) == {str(path) for path in files}


@pytest.mark.asyncio
async def test_collect_artifacts_returns_empty_for_clean_workspace(tmp_path: Path) -> None:
    """clean workspace では artifact list は空 tuple になる。"""

    adapter, workspace = await _prepared_workspace(tmp_path)

    assert await adapter.collect_artifacts(workspace) == ()


@pytest.mark.asyncio
async def test_collect_artifacts_handles_missing_workdir(tmp_path: Path) -> None:
    """cleanup 後の missing workdir は empty artifact list として扱う。"""

    adapter, workspace = await _prepared_workspace(tmp_path)
    await adapter.cleanup(workspace)

    assert await adapter.collect_artifacts(workspace) == ()


@pytest.mark.asyncio
async def test_cleanup_removes_workdir(tmp_path: Path) -> None:
    """cleanup は workspace directory を削除する。"""

    adapter, workspace = await _prepared_workspace(tmp_path)
    workdir = Path(workspace.workdir)

    assert workdir.exists()
    await adapter.cleanup(workspace)

    assert workdir.exists() is False


@pytest.mark.asyncio
async def test_cleanup_is_idempotent(tmp_path: Path) -> None:
    """cleanup は同じ workspace に対して複数回呼んでも error にしない。"""

    adapter, workspace = await _prepared_workspace(tmp_path)
    await adapter.cleanup(workspace)
    await adapter.cleanup(workspace)

    assert Path(workspace.workdir).exists() is False


def test_workspace_is_frozen() -> None:
    """RunnerWorkspace は server-owned workspace reference として immutable にする。"""

    workspace = RunnerWorkspace(
        run_id="run",
        workspace_id="0" * 32,
        workdir="/tmp/runner-run",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        workspace.workdir = "/tmp/changed"


def test_command_request_is_frozen() -> None:
    """RunnerCommandRequest は実行直前に差し替えられない immutable input にする。"""

    request = RunnerCommandRequest(argv=("python", "-V"), cwd="/tmp/runner-run")

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.argv = ("rm", "-rf", "/")


def test_command_result_is_frozen() -> None:
    """RunnerCommandResult は監査 record として immutable にする。"""

    result = RunnerCommandResult(
        exit_code=0,
        stdout_bytes=1,
        stderr_bytes=0,
        duration_seconds=0.1,
        timeout_reached=False,
        cancelled=False,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.exit_code = 1


def test_cancel_token_can_be_cancelled() -> None:
    """RunnerCancelToken は cancel 後に is_cancelled=True を返す。"""

    token = RunnerCancelToken()
    token.cancel()

    assert token.is_cancelled is True


def test_cancel_token_default_not_cancelled() -> None:
    """RunnerCancelToken は初期状態では cancelled ではない。"""

    token = RunnerCancelToken()

    assert token.is_cancelled is False


# Sprint 7 batch 2 BL-0074/0075/0076 integration tests


@POSIX_ONLY
@pytest.mark.asyncio
async def test_run_command_rejects_invalid_resource_policy(tmp_path: Path) -> None:
    """ResourcePolicy validate() に違反する policy は subprocess 前に reject。

    Codex R1 F-007 adopt: invalid policy は RunnerExecutionContext 経由で
    渡され、orchestrator-resolve 経路でも validate() が必ず通る。
    """
    from backend.app.services.runner.network_egress import NetworkPolicy
    from backend.app.services.runner.resource_cap import ResourcePolicy

    adapter, workspace = await _prepared_workspace(tmp_path)

    invalid_policy = ResourcePolicy(
        cpu_quota_us=-1,
        cpu_period_us=1_000_000,
        memory_bytes=1024,
        pids_max=10,
        disk_bytes=1024,
        wall_clock_seconds=1.0,
        output_byte_cap=1024,
        stdout_byte_cap=512,
        stderr_byte_cap=512,
    )
    invalid_context = RunnerExecutionContext(
        resource_policy=invalid_policy,
        network_policy=NetworkPolicy.p0_default(),
    )

    with pytest.raises(ValueError, match="resource_cap"):
        await adapter.run_command(
            workspace,
            RunnerCommandRequest(
                argv=("/bin/echo", "hello"),
                cwd=workspace.workdir,
            ),
            invalid_context,
        )


@POSIX_ONLY
@pytest.mark.asyncio
async def test_run_command_p0_default_policy_passes(tmp_path: Path) -> None:
    """P0 default RunnerExecutionContext では subprocess 実行が成立。"""
    adapter, workspace = await _prepared_workspace(tmp_path)

    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/echo", "hello"),
            cwd=workspace.workdir,
        ),
        RunnerExecutionContext.p0_default(),
    )
    assert result.exit_code == 0
    assert result.output_cap_exceeded is False


@POSIX_ONLY
@pytest.mark.asyncio
async def test_run_command_rejects_network_capable_command_in_deny_all(
    tmp_path: Path,
) -> None:
    """Codex R1 F-001 adopt: NetworkPolicy.mode=deny_all で curl / wget 等を deny."""
    adapter, workspace = await _prepared_workspace(tmp_path)

    with pytest.raises(ValueError, match="network_egress"):
        await adapter.run_command(
            workspace,
            RunnerCommandRequest(
                argv=("/usr/bin/curl", "https://example.com"),
                cwd=workspace.workdir,
            ),
            RunnerExecutionContext.p0_default(),
        )


@POSIX_ONLY
@pytest.mark.asyncio
async def test_run_command_scrubbed_env_keys_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """allowlist に入れた forbidden var は scrubbed_env_keys に記録される。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-LEAK")
    monkeypatch.setenv("HOME", "/home/user")

    adapter, workspace = await _prepared_workspace(tmp_path)

    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/echo", "ok"),
            cwd=workspace.workdir,
            env_allowlist=frozenset({"OPENAI_API_KEY", "HOME", "PATH"}),
        ),
        RunnerExecutionContext.p0_default(),
    )

    assert result.exit_code == 0
    # OPENAI_API_KEY must be in scrubbed list (audit invariant)
    assert "OPENAI_API_KEY" in result.scrubbed_env_keys
    # scrubbed_env_keys contains *names only*, no value
    for key in result.scrubbed_env_keys:
        assert "LEAK" not in key
        assert "sk-" not in key


@POSIX_ONLY
@pytest.mark.asyncio
async def test_run_command_pattern_based_env_scrub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """unknown VENDOR_X_TOKEN も pattern で scrub される。"""
    monkeypatch.setenv("ACME_VENDOR_TOKEN", "vendor-secret")

    adapter, workspace = await _prepared_workspace(tmp_path)

    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/echo", "ok"),
            cwd=workspace.workdir,
            env_allowlist=frozenset({"ACME_VENDOR_TOKEN", "PATH"}),
        ),
        RunnerExecutionContext.p0_default(),
    )

    assert result.exit_code == 0
    assert "ACME_VENDOR_TOKEN" in result.scrubbed_env_keys


def test_runner_command_request_has_no_policy_fields() -> None:
    """Codex R1 F-007 adopt: server-owned-boundary §1。RunnerCommandRequest は
    resource_policy / network_policy / timeout_seconds field を持たない。"""
    req = RunnerCommandRequest(argv=("a",), cwd="/tmp")
    assert not hasattr(req, "resource_policy")
    assert not hasattr(req, "network_policy")
    assert not hasattr(req, "timeout_seconds")


def test_runner_execution_context_p0_default() -> None:
    """RunnerExecutionContext.p0_default() = deny_all egress + P0 ResourcePolicy."""
    from backend.app.services.runner.network_egress import NetworkEgressMode
    from backend.app.services.runner.resource_cap import ResourcePolicy

    ctx = RunnerExecutionContext.p0_default()
    assert ctx.network_policy.mode == NetworkEgressMode.DENY_ALL
    assert ctx.resource_policy == ResourcePolicy.from_p0_defaults()


@POSIX_ONLY
@pytest.mark.asyncio
async def test_run_command_output_cap_triggers_immediate_kill(
    tmp_path: Path,
) -> None:
    """Codex SP7 R2 F-SP7-R2-002 adopt: output_byte_cap 超過時に
    wall_clock を待たず即時 kill。

    `yes` 相当の bounded output script を実行し、output_cap (8 KB) 超過で
    proc が wall_clock より遥かに短い時間で kill されることを verify。
    """
    import dataclasses

    from backend.app.services.runner.resource_cap import ResourcePolicy

    adapter, workspace = await _prepared_workspace(tmp_path)
    # 大量出力する script を workspace 内に作成
    script = Path(workspace.workdir) / "spam.sh"
    script.write_text(
        '#!/bin/sh\n'
        'i=0\n'
        'while [ $i -lt 100000 ]; do\n'
        '  printf "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n"\n'
        '  i=$((i+1))\n'
        'done\n'
    )
    script.chmod(0o755)

    # 8 KB cap で 100,000 行 × 33 bytes = 3.3 MB を生成しようとする → 即時 kill
    tight_policy = dataclasses.replace(
        ResourcePolicy.from_p0_defaults(),
        wall_clock_seconds=30.0,  # 30 sec timeout、kill されなければ 30 sec 待つ
        output_byte_cap=8 * 1024,
        stdout_byte_cap=4 * 1024,
        stderr_byte_cap=4 * 1024,
    )
    tight_context = dataclasses.replace(
        RunnerExecutionContext.p0_default(),
        resource_policy=tight_policy,
    )

    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/sh", str(script)),
            cwd=workspace.workdir,
        ),
        tight_context,
    )

    # output_cap_exceeded=True + wall_clock より遥かに短く終了
    assert result.output_cap_exceeded is True
    assert result.timeout_reached is False
    assert result.duration_seconds < 10.0


def test_runner_command_result_default_new_fields() -> None:
    """RunnerCommandResult の新 field (Sprint 7 batch 2) は default が安全側。"""
    result = RunnerCommandResult(
        exit_code=0,
        stdout_bytes=1,
        stderr_bytes=0,
        duration_seconds=0.1,
        timeout_reached=False,
        cancelled=False,
    )
    assert result.output_cap_exceeded is False
    assert result.scrubbed_env_keys == ()