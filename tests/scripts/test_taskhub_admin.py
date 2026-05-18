"""Sprint 12 batch 7: taskhub_admin.py CLI skeleton tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_PATH = _REPO_ROOT / "scripts" / "taskhub_admin.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(_CLI_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        check=False,
    )


def test_cli_script_exists() -> None:
    assert _CLI_PATH.exists(), f"CLI script not found at {_CLI_PATH}"


def test_cli_help_returns_zero() -> None:
    result = _run_cli("--help")
    assert result.returncode == 0
    assert "taskhub admin CLI" in result.stdout
    assert "ADR-00021" in result.stdout


def test_cli_no_subcommand_returns_exit_2() -> None:
    """サブコマンド未指定は argparse usage error (exit 2)."""
    result = _run_cli()
    assert result.returncode == 2
    assert "required" in result.stderr.lower() or "usage" in result.stderr.lower()


def test_cli_restore_requires_input() -> None:
    """`restore` は --input 必須 (argparse required=True で exit 2)."""
    result = _run_cli("restore")
    assert result.returncode == 2


def test_cli_restore_missing_input_path_returns_exit_2(tmp_path: Path) -> None:
    """存在しない --input → exit 2 (CLI usage error)."""
    missing = tmp_path / "nonexistent-backup.tar.age"
    result = _run_cli("restore", "--input", str(missing))
    assert result.returncode == 2
    assert "input backup file not found" in result.stderr


def test_cli_restore_skeleton_mode_returns_exit_1(tmp_path: Path) -> None:
    """input file 存在 → skeleton message + exit 1."""
    fake_backup = tmp_path / "fake-backup.tar.age"
    fake_backup.write_bytes(b"fake-age-encrypted-content")
    result = _run_cli("restore", "--input", str(fake_backup))
    assert result.returncode == 1
    assert "[SKELETON] taskhub restore" in result.stdout
    assert "age-encrypted tar" in result.stdout


def test_cli_migrate_requires_target() -> None:
    """`migrate` は --target 必須 (argparse required=True で exit 2)."""
    result = _run_cli("migrate")
    assert result.returncode == 2


def test_cli_migrate_skeleton_mode_returns_exit_1() -> None:
    """`migrate --target <host>` → skeleton + exit 1."""
    result = _run_cli("migrate", "--target", "example-host")
    assert result.returncode == 1
    assert "[SKELETON] taskhub migrate" in result.stdout
    assert "example-host" in result.stdout
    # default transport is "closed-network"
    assert "via closed-network" in result.stdout


def test_cli_migrate_via_scp_option() -> None:
    """`migrate --target <host> --via scp` を accepting する."""
    result = _run_cli("migrate", "--target", "example-host", "--via", "scp")
    assert result.returncode == 1
    assert "via scp" in result.stdout


def test_cli_status_skeleton_mode_returns_exit_1() -> None:
    """`status` → skeleton + exit 1."""
    result = _run_cli("status")
    assert result.returncode == 1
    assert "[SKELETON] taskhub status" in result.stdout
    assert "Docker service health" in result.stdout


def test_cli_age_rotate_skeleton_mode_returns_exit_1() -> None:
    """`age-rotate` → skeleton + exit 1, ADR-00021 §5 SOP 言及あり."""
    result = _run_cli("age-rotate")
    assert result.returncode == 1
    assert "[SKELETON] taskhub age-rotate" in result.stdout
    assert "ADR-00021 §5" in result.stdout


def test_cli_verify_requires_flag() -> None:
    """`verify` は --integrity / --network-invariant の少なくとも 1 つ必須."""
    result = _run_cli("verify")
    assert result.returncode == 2
    assert (
        "--integrity / --network-invariant required" in result.stderr
    )


def test_cli_verify_integrity_skeleton_mode_returns_exit_1() -> None:
    """`verify --integrity` → skeleton + exit 1."""
    result = _run_cli("verify", "--integrity")
    assert result.returncode == 1
    assert "[SKELETON] taskhub verify" in result.stdout
    assert "--integrity" in result.stdout


def test_cli_verify_network_invariant_skeleton_mode_returns_exit_1() -> None:
    """`verify --network-invariant` → skeleton + exit 1."""
    result = _run_cli("verify", "--network-invariant")
    assert result.returncode == 1
    assert "[SKELETON] taskhub verify" in result.stdout
    assert "--network-invariant" in result.stdout


def test_cli_verify_both_flags_skeleton_mode_returns_exit_1() -> None:
    """`verify --integrity --network-invariant` → skeleton + exit 1, 両方の文言含む."""
    result = _run_cli("verify", "--integrity", "--network-invariant")
    assert result.returncode == 1
    assert "[SKELETON] taskhub verify" in result.stdout
    assert "--integrity" in result.stdout
    assert "--network-invariant" in result.stdout
