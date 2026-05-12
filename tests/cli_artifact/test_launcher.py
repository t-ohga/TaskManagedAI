"""Sprint 6 BL-0065: launcher integration tests using ``/bin/sh`` as stub agent.

実際の ``codex`` binary を要求すると CI / dev で flake する。代わりに
``/bin/sh`` を allowed agent として temp registry で wire し、stdout / stderr
/ exit / timeout / cancel / env scrubbing / path containment / cwd allowlist
を検証。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

from backend.app.services.cli_artifact.launcher import (
    LauncherDenyReason,
    LauncherError,
    LauncherRunRequest,
    compute_text_hash,
    launch_cli_agent,
)
from backend.app.services.cli_artifact.registry import (
    AgentRegistryEntry,
    CliAgentRegistry,
)


def _make_registry_with_sh(
    cwd_base: str,
    *,
    name: str = "sh",
    argv: tuple[str, ...] = ("-c", "cat; printf >&2 'stderr-end\\n'"),
    stdin_source: str = "{prompt_file}",
    timeout: int = 10,
    max_stdout: int = 4096,
    max_stderr: int = 2048,
) -> CliAgentRegistry:
    entry = AgentRegistryEntry(
        name=name,
        binary_path="/bin/sh",
        argv_template=argv,
        stdin_source=stdin_source,
        env_passthrough=frozenset({"PATH", "LANG"}),
        timeout_seconds=timeout,
        max_stdout_bytes=max_stdout,
        max_stderr_bytes=max_stderr,
        max_payload_data_class="internal",
        cwd_allowlist=(cwd_base,),
    )
    return CliAgentRegistry(
        schema_version="1.0.0",
        agents=MappingProxyType({name: entry}),
    )


def _make_paths(tmp_path: Path, prompt: str) -> tuple[str, str, str]:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    output_file = tmp_path / "out.txt"
    output_file.write_text("", encoding="utf-8")
    stream_file = tmp_path / "stream.jsonl"
    stream_file.write_text("", encoding="utf-8")
    return str(prompt_file), str(output_file), str(stream_file)


def _make_request(
    tmp_path: Path,
    agent_name: str,
    prompt: str = "x",
) -> LauncherRunRequest:
    prompt_file, output_file, stream_file = _make_paths(tmp_path, prompt)
    return LauncherRunRequest(
        agent_name=agent_name,
        prompt_file=prompt_file,
        output_file=output_file,
        stream_file=stream_file,
        cwd=str(tmp_path),
    )


# --- happy path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_launch_succeeds_with_stub_agent(tmp_path: Path) -> None:
    registry = _make_registry_with_sh(str(tmp_path))
    request = _make_request(tmp_path, "sh", "hello\n")
    result = await launch_cli_agent(request, registry)
    assert result.agent_name == "sh"
    assert result.exit_code == 0
    assert result.timeout_reached is False
    assert result.cancelled is False
    assert result.stdout_bytes >= len("hello\n")
    assert result.stderr_bytes >= len("stderr-end\n")
    assert result.signal is None


# --- registry deny ----------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_agent_denied(tmp_path: Path) -> None:
    registry = _make_registry_with_sh(str(tmp_path))
    request = _make_request(tmp_path, "ghost")
    with pytest.raises(LauncherError) as exc:
        await launch_cli_agent(request, registry)
    assert exc.value.reason is LauncherDenyReason.AGENT_NOT_IN_REGISTRY


# --- cwd allowlist / path containment (server-owned-boundary §1) ------------


@pytest.mark.asyncio
async def test_cwd_outside_allowlist_denied(tmp_path: Path) -> None:
    other_dir = tmp_path.parent / "outside"
    other_dir.mkdir(exist_ok=True)
    registry = _make_registry_with_sh(str(tmp_path))
    # caller passes a cwd that is OUTSIDE the registry's cwd_allowlist
    request = LauncherRunRequest(
        agent_name="sh",
        prompt_file=str(tmp_path / "prompt.txt"),
        output_file=str(tmp_path / "out.txt"),
        stream_file=str(tmp_path / "stream.jsonl"),
        cwd=str(other_dir),
    )
    (tmp_path / "prompt.txt").write_text("x", encoding="utf-8")
    (tmp_path / "out.txt").write_text("", encoding="utf-8")
    (tmp_path / "stream.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(LauncherError) as exc:
        await launch_cli_agent(request, registry)
    assert exc.value.reason is LauncherDenyReason.CWD_OUTSIDE_ALLOWLIST


@pytest.mark.asyncio
async def test_prompt_file_outside_cwd_denied(tmp_path: Path) -> None:
    registry = _make_registry_with_sh(str(tmp_path))
    other = tmp_path.parent / "outside-prompt.txt"
    other.write_text("hello", encoding="utf-8")
    request = LauncherRunRequest(
        agent_name="sh",
        prompt_file=str(other),
        output_file=str(tmp_path / "out.txt"),
        stream_file=str(tmp_path / "stream.jsonl"),
        cwd=str(tmp_path),
    )
    (tmp_path / "out.txt").write_text("", encoding="utf-8")
    (tmp_path / "stream.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(LauncherError) as exc:
        await launch_cli_agent(request, registry)
    assert exc.value.reason is LauncherDenyReason.PATH_OUTSIDE_CWD


@pytest.mark.asyncio
async def test_traversal_path_resolves_outside_cwd(tmp_path: Path) -> None:
    registry = _make_registry_with_sh(str(tmp_path))
    # caller supplies "{tmp_path}/../etc/passwd" — Path.resolve() collapses ..
    request = LauncherRunRequest(
        agent_name="sh",
        prompt_file=f"{tmp_path}/../etc/passwd",
        output_file=str(tmp_path / "out.txt"),
        stream_file=str(tmp_path / "stream.jsonl"),
        cwd=str(tmp_path),
    )
    (tmp_path / "out.txt").write_text("", encoding="utf-8")
    (tmp_path / "stream.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(LauncherError) as exc:
        await launch_cli_agent(request, registry)
    assert exc.value.reason is LauncherDenyReason.PATH_OUTSIDE_CWD


@pytest.mark.asyncio
async def test_symlink_prompt_file_denied(tmp_path: Path) -> None:
    registry = _make_registry_with_sh(str(tmp_path))
    real_target = tmp_path / "real_prompt.txt"
    real_target.write_text("x", encoding="utf-8")
    symlink_path = tmp_path / "symlink_prompt.txt"
    os.symlink(str(real_target), str(symlink_path))
    request = LauncherRunRequest(
        agent_name="sh",
        prompt_file=str(symlink_path),
        output_file=str(tmp_path / "out.txt"),
        stream_file=str(tmp_path / "stream.jsonl"),
        cwd=str(tmp_path),
    )
    (tmp_path / "out.txt").write_text("", encoding="utf-8")
    (tmp_path / "stream.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(LauncherError) as exc:
        await launch_cli_agent(request, registry)
    assert exc.value.reason is LauncherDenyReason.PATH_IS_SYMLINK


# --- timeout / cancel -------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_terminates_subprocess(tmp_path: Path) -> None:
    registry = _make_registry_with_sh(
        str(tmp_path),
        name="sleeper",
        argv=("-c", "sleep 10"),
        stdin_source="",
        timeout=1,
    )
    request = _make_request(tmp_path, "sleeper")
    result = await launch_cli_agent(request, registry)
    assert result.timeout_reached is True
    assert result.signal in {"SIGTERM", "SIGKILL"}


@pytest.mark.asyncio
async def test_cancellation_propagates(tmp_path: Path) -> None:
    registry = _make_registry_with_sh(
        str(tmp_path),
        name="sleeper",
        argv=("-c", "sleep 30"),
        stdin_source="",
        timeout=300,
    )
    request = _make_request(tmp_path, "sleeper")

    async def _run() -> None:
        await launch_cli_agent(request, registry)

    task = asyncio.create_task(_run())
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# --- stdout / stderr caps ---------------------------------------------------


@pytest.mark.asyncio
async def test_stdout_is_capped(tmp_path: Path) -> None:
    registry = _make_registry_with_sh(
        str(tmp_path),
        name="spammer",
        argv=("-c", "yes ABC | head -c 200000"),
        stdin_source="",
        max_stdout=1024,
    )
    request = _make_request(tmp_path, "spammer")
    result = await launch_cli_agent(request, registry)
    assert result.stdout_bytes == 1024


# --- env scrubbing ----------------------------------------------------------


@pytest.mark.asyncio
async def test_secret_env_not_leaked_to_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OPENAI_API_KEY 等 forbidden var が env_passthrough にあっても
    registry __post_init__ で reject されることを確認 + 別途 launcher 内部の
    defense-in-depth も期待通り動くことを確認。"""

    with pytest.raises(ValueError, match="forbidden"):
        AgentRegistryEntry(
            name="leak",
            binary_path="/bin/sh",
            argv_template=("-c", "env"),
            stdin_source="",
            env_passthrough=frozenset({"PATH", "OPENAI_API_KEY"}),
            timeout_seconds=10,
            max_stdout_bytes=1024,
            max_stderr_bytes=1024,
            max_payload_data_class="internal",
            cwd_allowlist=(str(tmp_path),),
        )

    # PATH-only registry でも parent ENV の secret は subprocess に渡らない
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-canary-1234567890")
    registry = _make_registry_with_sh(
        str(tmp_path),
        name="echoer",
        argv=(
            "-c",
            'env | grep -E "^(OPENAI|ANTHROPIC|GITHUB|DATABASE)_" || echo NONE',
        ),
        stdin_source="",
    )
    request = _make_request(tmp_path, "echoer")
    result = await launch_cli_agent(request, registry)
    assert result.exit_code == 0


# --- binary missing ---------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_binary_denied(tmp_path: Path) -> None:
    entry = AgentRegistryEntry(
        name="ghost",
        binary_path="/nonexistent/path/to/binary-xyz",
        argv_template=("--help",),
        stdin_source="",
        env_passthrough=frozenset({"PATH"}),
        timeout_seconds=10,
        max_stdout_bytes=1024,
        max_stderr_bytes=1024,
        max_payload_data_class="internal",
        cwd_allowlist=(str(tmp_path),),
    )
    registry = CliAgentRegistry(
        schema_version="1.0.0",
        agents=MappingProxyType({"ghost": entry}),
    )
    request = _make_request(tmp_path, "ghost")
    with pytest.raises(LauncherError) as exc:
        await launch_cli_agent(request, registry)
    assert exc.value.reason is LauncherDenyReason.BINARY_NOT_FOUND


# --- AC-HARD-05 forbidden path -----------------------------------------------


@pytest.mark.parametrize(
    "forbidden_subpath",
    [
        ".git/config",
        ".env",
        "secrets/age.key",
        "migrations/0099_bad.py",
        ".github/workflows/ci.yml",
        # Codex SP6B1 R3 F-SP6B1-R3-002 + R4 F-SP6B1-R4-001 adopt: Codex /
        # Claude harness file 改ざん経路を deny する。
        ".codex/config.toml",
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".claude/CLAUDE.md",
        ".claude/hooks/agentrun/check.sh",
        ".claude/agents/foo.md",
        ".claude/skills/bar.md",
        ".claude/rules/baz.md",
        ".claude/reference/qux.md",
        ".claude/commands/quux.md",
    ],
)
@pytest.mark.asyncio
async def test_forbidden_path_denied_for_output_file(
    tmp_path: Path, forbidden_subpath: str
) -> None:
    """Codex SP6B1 R2 F-SP6B1-R2-001: launcher は cwd 配下であっても
    AC-HARD-05 forbidden path への書込を deny する。"""

    registry = _make_registry_with_sh(str(tmp_path))
    # 該当 forbidden path を tmp_path 配下に作る (parent ディレクトリ含む)
    target = tmp_path / forbidden_subpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()
    request = LauncherRunRequest(
        agent_name="sh",
        prompt_file=str(tmp_path / "prompt.txt"),
        output_file=str(target),
        stream_file=str(tmp_path / "stream.jsonl"),
        cwd=str(tmp_path),
    )
    (tmp_path / "prompt.txt").write_text("x", encoding="utf-8")
    (tmp_path / "stream.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(LauncherError) as exc:
        await launch_cli_agent(request, registry)
    assert exc.value.reason is LauncherDenyReason.PATH_FORBIDDEN


# --- absolute binary_path enforcement (Codex SP6B1 R2 F-SP6B1-R2-004) -------


@pytest.mark.asyncio
async def test_binary_must_be_absolute_path(tmp_path: Path) -> None:
    """registry 自体で reject されることを確認 (signature レベル削除)。"""

    with pytest.raises(ValueError, match="absolute path"):
        AgentRegistryEntry(
            name="bad",
            binary_path="sh",
            argv_template=("-c", "echo x"),
            stdin_source="",
            env_passthrough=frozenset({"PATH"}),
            timeout_seconds=10,
            max_stdout_bytes=1024,
            max_stderr_bytes=1024,
            max_payload_data_class="internal",
            cwd_allowlist=(str(tmp_path),),
        )


# --- caller-supplied signature physical removal -----------------------------


def test_run_request_has_no_payload_data_class_field() -> None:
    """server-owned-boundary §1 + Codex SP6B1 R1 F-SP6B1-001 採用:
    caller-supplied data class 経路が signature レベルで削除されていることを
    fail-fast で確認する。"""

    import dataclasses

    fields = {f.name for f in dataclasses.fields(LauncherRunRequest)}
    assert "payload_data_class" not in fields
    assert {"agent_name", "prompt_file", "output_file", "stream_file", "cwd"} <= fields


# --- helper -----------------------------------------------------------------


def test_compute_text_hash_is_sha256() -> None:
    import hashlib

    text = "hello world"
    assert compute_text_hash(text) == hashlib.sha256(text.encode()).hexdigest()


# --- skip on non-POSIX ------------------------------------------------------


def _skip_on_non_posix() -> None:
    if os.name != "posix":
        pytest.skip(f"launcher tests require POSIX shell, not {sys.platform}")


@pytest.fixture(autouse=True)
def _require_posix() -> None:
    _skip_on_non_posix()
