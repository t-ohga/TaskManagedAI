"""Sprint 12 batch 7: taskhub_admin.py CLI skeleton tests."""

from __future__ import annotations

import shutil
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


def test_cli_init_requires_host_and_tailnet() -> None:
    """`init` は --host + --tailnet 必須 (Codex R3 F-PR63-007 adopt、ADR-00021 §3 line 151)."""
    result = _run_cli("init")
    assert result.returncode == 2
    # --host だけでは不足 (--tailnet も必須)
    result_host_only = _run_cli("init", "--host", "t-ohga-vps")
    assert result_host_only.returncode == 2


def test_cli_init_skeleton_mode_matches_adr_drill_step4() -> None:
    """`init --host <name> --tailnet <ts.net>` → skeleton + exit 1 (host migration drill step 4)."""
    result = _run_cli(
        "init", "--host", "t-ohga-vps", "--tailnet", "tail-xxxxx.ts.net"
    )
    assert result.returncode == 1
    assert "[SKELETON] taskhub init" in result.stdout
    assert "t-ohga-vps" in result.stdout
    assert "tail-xxxxx.ts.net" in result.stdout


def test_cli_backup_requires_output() -> None:
    """`backup` は --output 必須 (argparse required=True で exit 2、Codex R2 F-PR63-004 adopt)."""
    result = _run_cli("backup")
    assert result.returncode == 2


def test_cli_backup_skeleton_mode_returns_exit_1(tmp_path: Path) -> None:
    """`backup --output <path>` → skeleton + exit 1 (drill 起点、ADR-00021 §3)."""
    target = tmp_path / "sp012-backup.tar.age"
    result = _run_cli("backup", "--output", str(target))
    assert result.returncode == 1
    assert "[SKELETON] taskhub backup" in result.stdout
    assert str(target) in result.stdout
    # default は SOPS-encrypted env 含めない
    assert "(with SOPS-encrypted .env)" not in result.stdout


def test_cli_backup_include_sops_env_option(tmp_path: Path) -> None:
    """`backup --include-sops-env` (PG-F-015 hardening rename、Codex R3 F-PR63-006 adopt)."""
    target = tmp_path / "secrets-backup.tar.age"
    result = _run_cli("backup", "--output", str(target), "--include-sops-env")
    assert result.returncode == 1
    assert "[SKELETON] taskhub backup" in result.stdout
    assert "(with SOPS-encrypted .env)" in result.stdout
    # age private key は絶対含めない invariant が message に明示される
    assert "age private key は" in result.stdout and "絶対含まない" in result.stdout


def test_cli_backup_old_include_secrets_flag_is_rejected(tmp_path: Path) -> None:
    """旧 --include-secrets flag は ADR-00021 §11.1 PG-F-015 fix で廃止、argparse reject."""
    target = tmp_path / "old-flag-backup.tar.age"
    result = _run_cli("backup", "--output", str(target), "--include-secrets")
    # argparse は未登録 flag に対して exit 2 + stderr に error
    assert result.returncode == 2
    assert "include-secrets" in result.stderr


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
    """`migrate --target <host>` → skeleton + exit 1 (default transport = tailscale per ADR-00021 §3 + SP-012 drill)."""
    result = _run_cli("migrate", "--target", "example-host")
    assert result.returncode == 1
    assert "[SKELETON] taskhub migrate" in result.stdout
    assert "example-host" in result.stdout
    # ADR-00021 §3 と SP-012 §128 host migration drill command と整合: `--via tailscale` が default
    assert "via tailscale" in result.stdout


def test_cli_migrate_via_tailscale_option_matches_adr_drill() -> None:
    """ADR-00021 §3 と SP-012 §128 host migration drill command `--via tailscale` を accepting する (Codex R1 adopt)."""
    result = _run_cli("migrate", "--target", "t-ohga-vps", "--via", "tailscale")
    assert result.returncode == 1
    assert "via tailscale" in result.stdout
    assert "t-ohga-vps" in result.stdout


def test_cli_migrate_via_scp_option() -> None:
    """`migrate --target <host> --via scp` を accepting する (代替 transport)."""
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
    """`verify` は --integrity / --network-invariant / --multi-agent の少なくとも 1 つ必須."""
    result = _run_cli("verify")
    assert result.returncode == 2
    assert (
        "--integrity / --network-invariant / --multi-agent required"
        in result.stderr
    )


def test_cli_verify_multi_agent_matches_adr_multi_agent_fixture() -> None:
    """`verify --multi-agent` → ADR-00021 §11.5 multi-agent table restore fixture (Codex R2 F-PR63-002 adopt)."""
    result = _run_cli("verify", "--multi-agent")
    assert result.returncode == 1
    assert "[SKELETON] taskhub verify" in result.stdout
    assert "--multi-agent" in result.stdout
    # ADR-00021 §11.5 で列挙された 5 table のうち少なくとも 1 つを参照
    assert "inter_agent_messages" in result.stdout


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


def test_cli_verify_integrity_with_multi_agent_matches_drill_command() -> None:
    """SP-012 §131 drill command `taskhub verify --integrity --multi-agent` を accepting する."""
    result = _run_cli("verify", "--integrity", "--multi-agent")
    assert result.returncode == 1
    assert "--integrity" in result.stdout
    assert "--multi-agent" in result.stdout


def test_taskhub_console_script_entry_point_installed() -> None:
    """ADR-00021 §3 + SP-012 §128 で `taskhub` executable で起動できる (Codex R2 F-PR63-003 adopt)."""
    taskhub_path = shutil.which("taskhub")
    assert taskhub_path is not None, (
        "`taskhub` console_script entry point not on PATH; "
        "ensure `uv sync` ran with pyproject.toml [project.scripts] entry"
    )


def test_taskhub_console_script_help_includes_subcommands() -> None:
    """`taskhub --help` で 7 subcommand 全件 (init/backup/restore/migrate/status/age-rotate/verify) を表示する."""
    taskhub_path = shutil.which("taskhub")
    if taskhub_path is None:
        # 上 test で fail 済、本 test は noop fallback
        return
    result = subprocess.run(  # noqa: S603
        [taskhub_path, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    for cmd in (
        "init",
        "backup",
        "restore",
        "migrate",
        "status",
        "age-rotate",
        "verify",
    ):
        assert cmd in result.stdout, f"missing subcommand `{cmd}` in taskhub --help"


def test_taskhub_console_script_help_shows_taskhub_prog_name() -> None:
    """`taskhub --help` の usage 行は `taskhub` を表示する (Codex R3 F-PR63-005 adopt、prog 名固定)."""
    taskhub_path = shutil.which("taskhub")
    if taskhub_path is None:
        return
    result = subprocess.run(  # noqa: S603
        [taskhub_path, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    # usage 行は `usage: taskhub ...` (旧 prog 名 `taskhub_admin` ではない)
    assert "usage: taskhub " in result.stdout
    assert "usage: taskhub_admin " not in result.stdout
