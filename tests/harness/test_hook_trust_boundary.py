"""SP-007 Phase 5 hook trust-boundary helper tests."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SCRIPT = REPO_ROOT / "scripts" / "regenerate-hook-manifest.sh"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify-hook-trust-root.sh"
PRETOOL_SNAPSHOT = REPO_ROOT / ".claude" / "hooks" / "system" / "pretool-bash-snapshot.sh"
POSTTOOL_DISPATCHER = REPO_ROOT / ".claude" / "hooks" / "system" / "posttool-bash-file-dispatcher.sh"


def run_command(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    input_text: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        args,
        cwd=REPO_ROOT,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def write_fake_wrapper(trust_root: Path) -> Path:
    wrapper = trust_root / "taskmanagedai-hook-wrapper.sh"
    wrapper.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--self-test" ]]; then
  test -n "${TASKMANAGEDAI_HOOK_REPO_ROOT:-}"
  test -f "${TASKMANAGEDAI_HOOK_MANIFEST:-}"
  test -d "${TASKMANAGEDAI_HOOK_STATE_DIR:-}"
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    wrapper.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return wrapper


def create_trust_root(tmp_path: Path) -> tuple[Path, Path, Path]:
    trust_root = tmp_path / "trusted"
    state_root = tmp_path / "trusted-state" / "taskmanagedai"
    trust_root.mkdir(mode=0o700)
    state_root.mkdir(parents=True, mode=0o700)
    write_fake_wrapper(trust_root)

    manifest = trust_root / "taskmanagedai-hook-manifest.sha256"
    result = run_command(
        [
            "/bin/bash",
            str(MANIFEST_SCRIPT),
            "--repo-root",
            str(REPO_ROOT),
            "--output",
            str(manifest),
        ]
    )
    assert result.returncode == 0, result.stderr
    manifest.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return trust_root, state_root, manifest


def test_regenerate_hook_manifest_stdout_is_sorted_and_relative() -> None:
    result = run_command(["/bin/bash", str(MANIFEST_SCRIPT), "--repo-root", str(REPO_ROOT), "--stdout"])

    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert lines
    paths = [line.split("  ", 1)[1] for line in lines]
    assert paths == sorted(paths)
    assert ".claude/hooks/system/posttool-bash-file-dispatcher.sh" in paths
    assert all(path.startswith(".claude/hooks/") for path in paths)
    assert all(str(REPO_ROOT) not in path for path in paths)


def test_regenerate_hook_manifest_requires_explicit_output_or_stdout() -> None:
    result = run_command(["/bin/bash", str(MANIFEST_SCRIPT), "--repo-root", str(REPO_ROOT)])

    assert result.returncode == 2
    assert "explicit --output or --stdout is required" in result.stderr


def test_verify_hook_trust_root_passes_with_temp_home_fixture(tmp_path: Path) -> None:
    trust_root, state_root, _manifest = create_trust_root(tmp_path)

    result = run_command(
        [
            "/bin/bash",
            str(VERIFY_SCRIPT),
            "--repo-root",
            str(REPO_ROOT),
            "--trust-root",
            str(trust_root),
            "--state-root",
            str(state_root),
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "manifest matches current repo hooks" in result.stdout
    assert "wrapper self-test passed" in result.stdout


def test_verify_hook_trust_root_rejects_manifest_mismatch(tmp_path: Path) -> None:
    trust_root, state_root, manifest = create_trust_root(tmp_path)
    manifest.write_text("0000  .claude/hooks/system/posttool-bash-file-dispatcher.sh\n", encoding="utf-8")

    result = run_command(
        [
            "/bin/bash",
            str(VERIFY_SCRIPT),
            "--repo-root",
            str(REPO_ROOT),
            "--trust-root",
            str(trust_root),
            "--state-root",
            str(state_root),
        ]
    )

    assert result.returncode == 2
    assert "manifest mismatch" in result.stderr


def test_verify_hook_trust_root_rejects_non_executable_wrapper(tmp_path: Path) -> None:
    trust_root, state_root, _manifest = create_trust_root(tmp_path)
    (trust_root / "taskmanagedai-hook-wrapper.sh").chmod(stat.S_IRUSR | stat.S_IWUSR)

    result = run_command(
        [
            "/bin/bash",
            str(VERIFY_SCRIPT),
            "--repo-root",
            str(REPO_ROOT),
            "--trust-root",
            str(trust_root),
            "--state-root",
            str(state_root),
        ]
    )

    assert result.returncode == 2
    assert "wrapper is not executable" in result.stderr


def test_bash_snapshot_hooks_honor_external_state_dir(tmp_path: Path) -> None:
    state_dir = tmp_path / "state" / "bash"
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
    env["TASKMANAGEDAI_HOOK_STATE_DIR"] = str(state_dir)

    pre = run_command(["/bin/bash", str(PRETOOL_SNAPSHOT)], env=env, input_text='{"tool_input":{"command":"true"}}')
    post = run_command(["/bin/bash", str(POSTTOOL_DISPATCHER)], env=env, input_text='{"tool_input":{"command":"true"}}')

    assert pre.returncode == 0, pre.stderr
    assert post.returncode == 0, post.stderr
    assert (state_dir / "last-pre.tsv").exists()
    assert (state_dir / "last-pre-meta.tsv").exists()
    assert (state_dir / "last-post.tsv").exists()


def test_post_dispatcher_fails_closed_when_external_state_dir_missing(tmp_path: Path) -> None:
    state_dir = tmp_path / "missing" / "bash"
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
    env["TASKMANAGEDAI_HOOK_STATE_DIR"] = str(state_dir)

    result = run_command(
        ["/bin/bash", str(POSTTOOL_DISPATCHER)],
        env=env,
        input_text='{"tool_input":{"command":"true"}}',
    )

    assert result.returncode == 2
    assert "state dir unavailable" in result.stdout
