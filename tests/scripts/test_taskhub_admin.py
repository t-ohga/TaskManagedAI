"""Sprint 12 batch 7: taskhub_admin.py CLI skeleton tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_PATH = _REPO_ROOT / "scripts" / "taskhub_admin.py"

# F-PR75-004 adopt: automation env を ambient から strip して subprocess inherit を防ぐ
# (CI run で GITHUB_ACTIONS / CI 等が leak し、destructive subcommand が default deny → 既存 test fail)
_AUTOMATION_ENV_VARS = (
    "SYSTEMD_INVOCATION_ID", "INVOCATION_ID", "JOURNAL_STREAM", "CRON_INVOCATION",
    "GITHUB_ACTIONS", "CI", "BUILD_ID", "BUILD_NUMBER", "RUN_ID",
    "KUBERNETES_SERVICE_HOST", "container", "BASH_EXECUTION_STRING",
)


def _sanitized_env() -> dict[str, str]:
    """ambient parent env から automation hints を strip した default env."""
    env = dict(os.environ)
    for var in _AUTOMATION_ENV_VARS:
        env.pop(var, None)
    return env


def _run_cli(
    *args: str, env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    # R2-F-005 + F-PR75-004 adopt: env override 引数追加 (security integration tests で
    # HOME=tmp_path を渡すために必要)。caller が env=None なら sanitized_env (automation 削除)。
    return subprocess.run(  # noqa: S603
        [sys.executable, str(_CLI_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        check=False,
        env=env if env is not None else _sanitized_env(),
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


def test_cli_backup_skeleton_escape_rejected(tmp_path: Path) -> None:
    """SP022-T02 Phase 2 / T08 batch 2: backup は real I/O 化、--allow-unsigned-manual-skeleton 物理 deny。

    R2-F-001 adopt: skeleton escape flag は backup では reject (real I/O は signed approval 必須)。
    """
    target = tmp_path / "sp012-backup.tar.age"
    result = _run_cli("backup", "--output", str(target), "--allow-unsigned-manual-skeleton")
    assert result.returncode == 2
    assert "rejected for backup subcommand" in result.stderr


def test_cli_backup_include_sops_env_arg_accepted_argparse(tmp_path: Path) -> None:
    """`backup --include-sops-env` は引き続き argparse 受容、age public key 不在で early exit 2 になることを verify。"""
    target = tmp_path / "secrets-backup.tar.age"
    # No approval_id, no allow_unsigned_manual_skeleton → manual destructive denied at gate (exit 2)
    # OR age public key not found → exit 2 earlier
    result = _run_cli(
        "backup", "--output", str(target), "--include-sops-env",
    )
    # default deny → exit 2、stderr に detail
    assert result.returncode == 2


def test_cli_backup_old_include_secrets_flag_is_rejected(tmp_path: Path) -> None:
    """旧 --include-secrets flag は ADR-00021 §11.1 PG-F-015 fix で廃止、argparse reject."""
    target = tmp_path / "old-flag-backup.tar.age"
    result = _run_cli("backup", "--output", str(target), "--include-secrets")
    # argparse は未登録 flag に対して exit 2 + stderr に error
    assert result.returncode == 2
    assert "include-secrets" in result.stderr


def test_cli_restore_requires_input_or_rollback() -> None:
    """`restore` は --input または --rollback のいずれかが必須."""
    result = _run_cli("restore")
    assert result.returncode == 2
    assert "--rollback" in result.stderr or "必須" in result.stderr


def test_cli_restore_input_and_rollback_are_mutually_exclusive(tmp_path: Path) -> None:
    """`restore --input ... --rollback ...` は exit 2 (排他)."""
    backup = tmp_path / "fake-backup.tar.age"
    backup.write_bytes(b"fake")
    result = _run_cli(
        "restore",
        "--input",
        str(backup),
        "--rollback",
        "2026-05-18T10-00-00",
    )
    assert result.returncode == 2
    assert "排他" in result.stderr or "mutually" in result.stderr.lower()


def test_cli_restore_rollback_allow_unsigned_skeleton_rejected() -> None:
    """SP022-T02 Phase 3 adopt (R3-F-001 fix): restore で `--allow-unsigned-manual-skeleton` は
    物理 deny (skeleton 経路は real I/O への path-collision/data-loss を許容しないため)。
    """
    result = _run_cli(
        "restore", "--rollback", "2026-05-18T10-00-00",
        "--allow-unsigned-manual-skeleton",
    )
    assert result.returncode == 2
    assert "restore_allow_unsigned_skeleton_rejected" in result.stderr


def test_cli_restore_missing_input_path_returns_exit_2(tmp_path: Path) -> None:
    """存在しない --input → exit 2 (CLI usage error)."""
    missing = tmp_path / "nonexistent-backup.tar.age"
    result = _run_cli("restore", "--input", str(missing))
    assert result.returncode == 2
    assert "input backup file not found" in result.stderr


def test_cli_restore_input_allow_unsigned_skeleton_rejected(tmp_path: Path) -> None:
    """SP022-T02 Phase 3 adopt (R3-F-001 fix): restore `--input` で `--allow-unsigned-manual-skeleton`
    は物理 deny。real I/O は signed approval + restore_claim 経由のみ。
    """
    fake_backup = tmp_path / "fake-backup.tar.age"
    fake_backup.write_bytes(b"fake-age-encrypted-content")
    result = _run_cli(
        "restore", "--input", str(fake_backup), "--allow-unsigned-manual-skeleton",
    )
    assert result.returncode == 2
    assert "restore_allow_unsigned_skeleton_rejected" in result.stderr


def test_cli_migrate_requires_target() -> None:
    """`migrate` は --target 必須 (argparse required=True で exit 2)."""
    result = _run_cli("migrate")
    assert result.returncode == 2


def test_cli_migrate_skeleton_mode_returns_exit_1() -> None:
    """`migrate --target <host>` → skeleton + exit 1 (default transport = tailscale per ADR-00021 §3 + SP-012 drill).

    SP022-T02 Phase 1: skeleton mode 確認は escape flag 付与。
    """
    result = _run_cli(
        "migrate", "--target", "example-host", "--allow-unsigned-manual-skeleton",
    )
    assert result.returncode == 1
    assert "[SKELETON] taskhub migrate" in result.stdout
    assert "example-host" in result.stdout
    # ADR-00021 §3 と SP-012 §128 host migration drill command と整合: `--via tailscale` が default
    assert "via tailscale" in result.stdout


def test_cli_migrate_via_tailscale_option_matches_adr_drill() -> None:
    """ADR-00021 §3 と SP-012 §128 host migration drill command `--via tailscale` を accepting する (Codex R1 adopt).

    SP022-T02 Phase 1: skeleton mode 確認は escape flag 付与。
    """
    result = _run_cli(
        "migrate", "--target", "t-ohga-vps", "--via", "tailscale",
        "--allow-unsigned-manual-skeleton",
    )
    assert result.returncode == 1
    assert "via tailscale" in result.stdout
    assert "t-ohga-vps" in result.stdout


def test_cli_migrate_via_scp_option() -> None:
    """`migrate --target <host> --via scp` を accepting する (代替 transport).

    SP022-T02 Phase 1: skeleton mode 確認は escape flag 付与。
    """
    result = _run_cli(
        "migrate", "--target", "example-host", "--via", "scp",
        "--allow-unsigned-manual-skeleton",
    )
    assert result.returncode == 1
    assert "via scp" in result.stdout


def test_cli_status_skeleton_mode_returns_exit_1() -> None:
    """`status` (flag なし) → skeleton + exit 1."""
    result = _run_cli("status")
    assert result.returncode == 1
    assert "[SKELETON] taskhub status" in result.stdout
    assert "Docker service health" in result.stdout


def test_cli_status_age_safety_flag_matches_pga_f_001(tmp_path: Path) -> None:
    """`status --age-safety` (ADR-00021 §14.1 PGA-F-001、Codex R4 F-PR63-008 adopt)."""
    del tmp_path
    result = _run_cli("status", "--age-safety")
    assert result.returncode == 1
    assert "[SKELETON] taskhub status" in result.stdout
    assert "--age-safety" in result.stdout
    assert "FileVault" in result.stdout


def test_cli_status_mac_preflight_flag_matches_pga_f_006() -> None:
    """`status --mac-preflight` (ADR-00021 §14.2 PGA-F-006)."""
    result = _run_cli("status", "--mac-preflight")
    assert result.returncode == 1
    assert "--mac-preflight" in result.stdout
    assert "pmset" in result.stdout or "sleep" in result.stdout


def test_cli_status_remote_split_brain_check(tmp_path: Path) -> None:
    """SP022-T02 Phase 4 real I/O: `status --remote <host>` returns JSON summary + exit 1 for unsafe.

    signed config 不在 → reason_code=remote_status_config_missing + split_brain_safe=False + exit 1.
    """
    env = _sanitized_env()
    env["HOME"] = str(tmp_path)
    result = _run_cli("status", "--remote", "old-host.example", env=env)
    assert result.returncode == 1
    summary = json.loads(result.stdout)
    assert summary["remote_host"] == "old-host.example"
    assert summary["reason_code"] == "remote_status_config_missing"
    assert summary["split_brain_safe"] is False


def test_cli_freeze_requires_reason() -> None:
    """`freeze` は --reason 必須 (Codex R4 F-PR63-012 adopt、ADR-00021 §11.2 split-brain prevention)."""
    result = _run_cli("freeze")
    assert result.returncode == 2


def test_cli_freeze_skeleton_mode_returns_exit_1() -> None:
    """`freeze --reason <text>` → skeleton + exit 1.

    SP022-T02 Phase 1: skeleton mode 確認は escape flag 付与。
    """
    result = _run_cli(
        "freeze", "--reason", "migration to t-ohga-vps at 2026-05-18T10:00Z",
        "--allow-unsigned-manual-skeleton",
    )
    assert result.returncode == 1
    assert "[SKELETON] taskhub freeze" in result.stdout
    assert "signed freeze marker" in result.stdout
    assert "thaw" in result.stdout


def test_cli_thaw_skeleton_mode_returns_exit_1() -> None:
    """`thaw` (flag なし) → skeleton + exit 1 (Codex R4 F-PR63-009 adopt、ADR-00021 §670).

    SP022-T02 Phase 1: skeleton mode 確認は escape flag 付与。
    """
    result = _run_cli("thaw", "--allow-unsigned-manual-skeleton")
    assert result.returncode == 1
    assert "[SKELETON] taskhub thaw" in result.stdout
    assert "preflight" in result.stdout
    # default 時は target active marker 削除に伴う説明が含まれない
    # (flag mode との差別化: 説明文の prefix `--decommission-target に伴う` で判定)
    assert "--decommission-target に伴う" not in result.stdout


def test_cli_thaw_decommission_target_flag() -> None:
    """`thaw --decommission-target` → 2-party-control + 別 actor approval invariant 言及あり.

    SP022-T02 Phase 1: skeleton mode 確認は escape flag 付与。
    """
    result = _run_cli(
        "thaw", "--decommission-target", "--allow-unsigned-manual-skeleton",
    )
    assert result.returncode == 1
    assert "[SKELETON] taskhub thaw" in result.stdout
    # flag 有効時は default にない説明 prefix が含まれる
    assert "--decommission-target に伴う" in result.stdout
    assert "別 actor approval" in result.stdout


def test_cli_active_registry_skeleton_mode_returns_exit_1() -> None:
    """`active-registry` → skeleton + exit 1 (Codex R4 F-PR63-010 adopt、ADR-00021 §670)."""
    result = _run_cli("active-registry")
    assert result.returncode == 1
    assert "[SKELETON] taskhub active-registry" in result.stdout
    assert "signed active ledger" in result.stdout
    assert "split-brain" in result.stdout


def test_cli_age_rotate_skeleton_mode_returns_exit_1() -> None:
    """`age-rotate` → skeleton + exit 1, ADR-00021 §5 SOP 言及あり.

    SP022-T02 Phase 1: skeleton mode 確認は escape flag 付与。
    """
    result = _run_cli("age-rotate", "--allow-unsigned-manual-skeleton")
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
    """`taskhub --help` で 10 subcommand 全件を表示する.

    expected subcommands: init / backup / restore / freeze / thaw /
    active-registry / migrate / status / age-rotate / verify
    """
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
        "freeze",
        "thaw",
        "active-registry",
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


# ---- SP022-T08 batch 1: signed journal offline JSONL CLI integration (6 fixture) ----


def _write_event_jsonl(tmp_path: Path, payloads: list[dict]) -> Path:
    """Helper: write event_payload list as JSONL with full schema."""
    p = tmp_path / "events.jsonl"
    lines = []
    for i, payload in enumerate(payloads, start=1):
        event = {
            "id": f"00000000-0000-0000-0000-{i:012d}",
            "event_type": "approval_requested",
            "tenant_id": 1,
            "actor_id": "00000000-0000-0000-0000-000000000099",
            "principal_id": None,
            "correlation_id": None,
            "trace_id": None,
            "event_payload": payload,
            "created_at": "2026-05-20T00:00:00+00:00",
        }
        lines.append(json.dumps(event))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_cli_verify_signed_journal_requires_input() -> None:
    """SP022-T08 batch 1: --signed-journal 単独 → exit 2."""
    result = _run_cli("verify", "--signed-journal")
    assert result.returncode == 2
    assert "requires --input" in result.stderr


def test_cli_verify_signed_journal_valid_jsonl_passes(tmp_path: Path) -> None:
    """SP022-T08 batch 1: valid JSONL → exit 0、stdout に final_hash."""
    p = _write_event_jsonl(tmp_path, [{"k": "v"}, {"k2": "v2"}])
    result = _run_cli("verify", "--signed-journal", "--input", str(p))
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["entry_count"] == 2
    assert len(out["final_hash"]) == 64
    assert out["reason_code"] == "signed_journal_offline_hash_computed"
    assert out["verification_performed"] is False


def test_cli_verify_signed_journal_tamper_detected(tmp_path: Path) -> None:
    """SP022-T08 batch 1: --expected-final-hash mismatch → exit 1 tamper detection."""
    p = _write_event_jsonl(tmp_path, [{"k": "v"}])
    # All-zero hash mismatch
    fake_hash = "0" * 64
    result = _run_cli("verify", "--signed-journal", "--input", str(p),
                      "--expected-final-hash", fake_hash)
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert out["tamper_detected"] is True
    assert out["reason_code"] == "signed_journal_offline_expected_hash_mismatch"


def test_cli_verify_signed_journal_mutually_exclusive_with_skeleton_flags(tmp_path: Path) -> None:
    """R2-F-002 adopt: --signed-journal + --integrity 同時 → exit 2 (parse-time validation)."""
    p = _write_event_jsonl(tmp_path, [{"k": "v"}])
    result = _run_cli("verify", "--signed-journal", "--input", str(p), "--integrity")
    assert result.returncode == 2
    assert "併用不可" in result.stderr or "exclusive" in result.stderr.lower()


def test_cli_verify_signed_journal_stdin_mode(tmp_path: Path) -> None:
    """R1-F-011 adopt: --input - (stdin) で file mode と同 final_hash."""
    p = _write_event_jsonl(tmp_path, [{"k": "v"}])
    file_result = _run_cli("verify", "--signed-journal", "--input", str(p))
    file_out = json.loads(file_result.stdout)
    file_hash = file_out["final_hash"]

    # Run again via stdin
    stdin_input = p.read_text(encoding="utf-8")
    stdin_result = subprocess.run(  # noqa: S603
        [sys.executable, str(_CLI_PATH), "verify", "--signed-journal", "--input", "-"],
        capture_output=True, text=True, cwd=str(_REPO_ROOT), check=False,
        input=stdin_input, env=_sanitized_env(),
    )
    assert stdin_result.returncode == 0, stdin_result.stderr
    stdin_out = json.loads(stdin_result.stdout)
    assert stdin_out["final_hash"] == file_hash


def test_cli_verify_signed_journal_expected_hash_invalid_arg_exits_2(tmp_path: Path) -> None:
    """R1-F-007 adopt: 不正な expected_final_hash → exit 2 usage error."""
    p = _write_event_jsonl(tmp_path, [{"k": "v"}])
    # uppercase hex
    result = _run_cli("verify", "--signed-journal", "--input", str(p),
                      "--expected-final-hash", "A" * 64)
    assert result.returncode == 2
    assert "expected_hash_invalid" in result.stderr or "hex" in result.stderr.lower()
