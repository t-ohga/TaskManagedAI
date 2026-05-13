# ruff: noqa: S108, ASYNC240
"""Sprint 7 BL-0071: RunnerAdapter interface and mock runner tests."""

from __future__ import annotations

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
            timeout_seconds=5,
        ),
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
        )


@pytest.mark.asyncio
async def test_run_command_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    """workspace prefix 偽装を含む outside cwd を containment check で拒否する。"""

    adapter, workspace = await _prepared_workspace(tmp_path)
    outside = Path(workspace.workdir + "-escape")
    outside.mkdir()

    with pytest.raises(ValueError, match="inside workspace"):
        await adapter.run_command(
            workspace,
            RunnerCommandRequest(
                argv=("/bin/echo", "should-not-run"),
                cwd=str(outside),
            ),
        )


@pytest.mark.asyncio
async def test_run_command_timeout(tmp_path: Path) -> None:
    """timeout_seconds を超えた process は terminate され timeout flag を返す。"""

    adapter, workspace = await _prepared_workspace(tmp_path)
    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/sleep", "10"),
            cwd=workspace.workdir,
            timeout_seconds=0.2,
        ),
    )

    assert result.timeout_reached is True
    assert result.cancelled is False
    assert result.duration_seconds < 5


@pytest.mark.asyncio
async def test_run_command_cancel_token(tmp_path: Path) -> None:
    """cancel_token が cancelled の場合は result.cancelled に反映する。"""

    adapter, workspace = await _prepared_workspace(tmp_path)
    cancel_token = RunnerCancelToken()
    cancel_token.cancel()

    result = await adapter.run_command(
        workspace,
        RunnerCommandRequest(
            argv=("/bin/echo", "ok"),
            cwd=workspace.workdir,
            timeout_seconds=5,
        ),
        cancel_token=cancel_token,
    )

    assert result.exit_code == 0
    assert result.cancelled is True


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
            timeout_seconds=5,
        ),
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
            timeout_seconds=5,
        ),
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
            timeout_seconds=5,
        ),
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
            timeout_seconds=5,
        ),
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