"""SP022-T02 Phase 1: taskhub_admin signed approval gate integration tests (subprocess).

R2-F-005 adopt: subprocess test では `HOME=tmp_path` env を渡し、`Path.home()` を
tmp_path に redirect。`_run_cli` helper に env 引数追加済 (test_taskhub_admin.py 同型)。

R3-F-001 adopt: fingerprint allowlist は repo-internal 固定 path のため、subprocess
レベルでは allowlist 操作不可。本 file は CLI gate boundary の **default deny / escape /
audit emission** に絞った 8 fixture を提供。signed approval verify の full path は
test_taskhub_signed_approval.py で network。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_PATH = _REPO_ROOT / "scripts" / "taskhub_admin.py"


def _run_cli_with_env(
    *args: str, env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run taskhub_admin.py with HOME redirected to tmp_path."""
    env = dict(os.environ)
    # Strip automation env vars by default
    for var in (
        "SYSTEMD_INVOCATION_ID", "INVOCATION_ID", "JOURNAL_STREAM", "CRON_INVOCATION",
        "GITHUB_ACTIONS", "CI", "BUILD_ID", "BUILD_NUMBER", "RUN_ID",
        "KUBERNETES_SERVICE_HOST", "container", "BASH_EXECUTION_STRING",
    ):
        env.pop(var, None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(  # noqa: S603
        [sys.executable, str(_CLI_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        check=False,
        env=env,
    )


def test_backup_manual_without_approval_denies_by_default(tmp_path: Path) -> None:
    """R1-F-002 adopt: destructive manual exec は default deny."""
    target = tmp_path / "out.tar.age"
    result = _run_cli_with_env(
        "backup", "--output", str(target),
        env_overrides={"HOME": str(tmp_path)},
    )
    assert result.returncode == 2
    assert "destructive_requires_approval" in result.stderr


def test_backup_manual_with_allow_unsigned_skeleton_proceeds(tmp_path: Path) -> None:
    """R1-F-002 adopt: --allow-unsigned-manual-skeleton で escape (Phase 1 only)."""
    target = tmp_path / "out.tar.age"
    result = _run_cli_with_env(
        "backup", "--output", str(target), "--allow-unsigned-manual-skeleton",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert result.returncode == 1  # skeleton mode
    assert "[SKELETON] taskhub backup" in result.stdout
    # audit marker contains unsigned_manual_skeleton_used=true
    assert "unsigned_manual_skeleton_used" in result.stderr


def test_backup_with_automation_env_without_flag_denies(tmp_path: Path) -> None:
    """R1-F-002 + R1-F-003 adopt: cron env + --from-automation なし → deny."""
    target = tmp_path / "out.tar.age"
    result = _run_cli_with_env(
        "backup", "--output", str(target),
        env_overrides={
            "HOME": str(tmp_path),
            "SYSTEMD_INVOCATION_ID": "fake-systemd-id",
        },
    )
    assert result.returncode == 2
    assert "automation_detected_without_flag" in result.stderr


def test_migrate_with_target_host_mismatch_denies(tmp_path: Path) -> None:
    """R2-F-003 adopt: signed approval target_host と CLI --target 不一致 → deny.

    注: 実 approval record と verify key を tmp に置く必要があるが、fingerprint allowlist は
    repo-internal 固定。本 test は **approval なし手動実行 + 別 --target** を default deny で
    確認する compromise (full target_host mismatch 検査は test_taskhub_signed_approval.py
    の unit-level で実施済)。
    """
    result = _run_cli_with_env(
        "migrate", "--target", "t-ohga-linux",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert result.returncode == 2
    # default deny で stop (approval ID 未指定のため)
    assert "destructive_requires_approval" in result.stderr


def test_status_no_approval_required(tmp_path: Path) -> None:
    """non-destructive subcommand は approval gate を呼ばない (audit emission なし)."""
    result = _run_cli_with_env(
        "status",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert result.returncode == 1  # skeleton mode
    assert "[SKELETON] taskhub status" in result.stdout
    # non-destructive subcommand では audit emission しない (overhead 回避、
    # destructive subcommand のみ gate を通過する設計)
    assert "AUDIT taskhub_signed_approval_gate" not in result.stderr
    # `ERROR: signed approval gate denied` も含まれないこと
    assert "signed approval gate denied" not in result.stderr


def test_audit_event_payload_allowlist_enforced(tmp_path: Path) -> None:
    """R1-F-010 adopt: audit payload に raw secret 含まれない invariant."""
    target = tmp_path / "out.tar.age"
    result = _run_cli_with_env(
        "backup", "--output", str(target),
        env_overrides={"HOME": str(tmp_path)},
    )
    # parse AUDIT line from stderr
    audit_line = None
    for line in result.stderr.splitlines():
        if line.startswith("AUDIT taskhub_signed_approval_gate:"):
            audit_line = line[len("AUDIT taskhub_signed_approval_gate:"):].strip()
            break
    assert audit_line is not None
    payload = json.loads(audit_line)
    # raw secret / signature / signing_key 等が含まれない
    forbidden_keys = {"signature", "signing_key", "raw_secret", "private_key", "reason"}
    assert not (set(payload.keys()) & forbidden_keys), payload.keys()
    # allowlist 内 key のみ (audit_marker + reason_code + ...)
    assert "reason_code" in payload
    assert "audit_marker" in payload
    assert payload["audit_marker"] == "taskhub_signed_approval_gate"


def test_destructive_subcommand_with_automation_env_and_no_approval_denies(tmp_path: Path) -> None:
    """R1-F-002 adopt: CI env + --from-automation なし、approval なし → both deny path verify."""
    target = tmp_path / "out.tar.age"
    result = _run_cli_with_env(
        "backup", "--output", str(target),
        env_overrides={
            "HOME": str(tmp_path),
            "CI": "true",
            "GITHUB_ACTIONS": "true",
        },
    )
    assert result.returncode == 2
    # automation_detected_without_flag が先に発火
    assert "automation_detected_without_flag" in result.stderr


def test_destructive_from_automation_without_approval_id_denies(tmp_path: Path) -> None:
    """R1-F-002 adopt: --from-automation 指定 + --approval-id なし → deny."""
    target = tmp_path / "out.tar.age"
    result = _run_cli_with_env(
        "backup", "--output", str(target), "--from-automation",
        env_overrides={
            "HOME": str(tmp_path),
            "CI": "true",
        },
    )
    assert result.returncode == 2
    assert "from_automation_requires_approval_id" in result.stderr
