"""Drill timer alert-only enforcement pytest fixture (SP022-T03 ADR-00021 §14.2 #4 PGA-F-013).

R1+R2 で 19 findings 全件 adopt 反映済、R3 CRITICAL clean。本 pytest fixture は
scanner (`scripts.ci._drill_timer_scanner`) を直接 invoke して violation / pass を verify。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNER = REPO_ROOT / "scripts/ci/_drill_timer_scanner.py"


def _run_scanner_baseline(tmp_path: Path) -> tuple[int, str]:
    """Run scanner in baseline-scan mode against tmp_path as cwd."""
    result = subprocess.run(  # noqa: S603 (sys.executable + repo-internal scanner path)
        [sys.executable, str(SCANNER), "--mode=baseline-scan"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def _write_drill_timer_and_service(
    tmp_path: Path, exec_command: str, *, timer_name: str = "taskhub-drill-alert"
) -> tuple[Path, Path]:
    """Write paired .timer / .service files at tmp_path/deploy/ for testing."""
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    timer = deploy_dir / f"{timer_name}.timer"
    service = deploy_dir / f"{timer_name}.service"
    timer.write_text(
        f"[Unit]\nDescription=Half-yearly drill alert\n\n"
        f"[Timer]\nOnCalendar=*-01,07-01 09:00:00\n"
        f"Unit={timer_name}.service\n\n"
        f"[Install]\nWantedBy=timers.target\n",
        encoding="utf-8",
    )
    service.write_text(
        f"[Unit]\nDescription=Drill alert\n\n[Service]\nType=oneshot\n"
        f"ExecStart={exec_command}\n",
        encoding="utf-8",
    )
    return timer, service


# ---- 1. positive deny: destructive command in ExecStart ----
def test_systemd_taskhub_migrate_rejected(tmp_path: Path) -> None:
    _write_drill_timer_and_service(tmp_path, "/usr/local/bin/taskhub migrate --target vps")
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "framework_intake_violation_drill_timer_alert_only_destructive_command" in output
    assert "taskhub_destructive_subcommand" in output


def test_systemd_docker_compose_down_rejected(tmp_path: Path) -> None:
    _write_drill_timer_and_service(tmp_path, "/usr/bin/docker compose down")
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "docker_compose_destructive" in output


def test_systemd_rm_rf_rejected(tmp_path: Path) -> None:
    _write_drill_timer_and_service(tmp_path, "/bin/rm -rf /var/log/taskhub")
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "rm_destructive" in output


def test_systemd_unknown_command_rejected(tmp_path: Path) -> None:
    _write_drill_timer_and_service(tmp_path, "/usr/local/bin/unknown-tool --foo")
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "framework_intake_violation_drill_timer_alert_only_unknown_command" in output


def test_cron_taskhub_restore_rejected(tmp_path: Path) -> None:
    cron_d = tmp_path / "etc" / "cron.d"
    cron_d.mkdir(parents=True)
    (cron_d / "drill-cron").write_text(
        "0 9 1 1,7 * root /usr/local/bin/taskhub restore --input /tmp/bk.age\n",
        encoding="utf-8",
    )
    # also need a paired drill timer file for scope match — but cron.d glob does not need timer
    # alongside; scanner picks cron.d separately. We still emit one drill timer to be sure scope
    # is active in real env (here baseline-scan picks cron.d directly via SCAN_CRON_GLOBS).
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "framework_intake_violation_drill_timer_alert_only_destructive_command" in output


# ---- 2. positive pass: notification commands ----
def test_systemd_notify_send_passes(tmp_path: Path) -> None:
    _write_drill_timer_and_service(
        tmp_path, '/usr/bin/notify-send "Drill due" "Half-yearly host migration"'
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 0, f"expected pass, got exit={exit_code} output={output}"


def test_systemd_osascript_passes(tmp_path: Path) -> None:
    _write_drill_timer_and_service(
        tmp_path,
        "/usr/bin/osascript -e display notification Drill due with title TaskManagedAI",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 0, f"expected pass, got exit={exit_code} output={output}"


def test_cron_slack_cli_passes(tmp_path: Path) -> None:
    cron_d = tmp_path / "etc" / "cron.d"
    cron_d.mkdir(parents=True)
    (cron_d / "drill-cron").write_text(
        "0 9 1 1,7 * root /usr/local/bin/slack-cli chat send --channel ops Half-yearly drill\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 0, f"expected pass, got exit={exit_code} output={output}"


def test_systemd_logger_passes(tmp_path: Path) -> None:
    _write_drill_timer_and_service(tmp_path, "/usr/bin/logger -t taskhub-drill Drill due")
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 0, f"expected pass, got exit={exit_code} output={output}"


# ---- 3. negative: empty repo ----
def test_empty_repo_passes(tmp_path: Path) -> None:
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 0, f"expected pass, got exit={exit_code} output={output}"


# ---- 4. edge: malformed quotes → fail-closed ----
def test_malformed_quotes_rejected(tmp_path: Path) -> None:
    _write_drill_timer_and_service(tmp_path, '/usr/bin/slack-cli "unclosed quote arg')
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "shlex_parse_failed" in output


# ---- 5. R2 F-PR70-T03-R2-002 adopt: stdin redirect bypass ----
def test_mail_stdin_redirect_rejected(tmp_path: Path) -> None:
    """`mail -s drill ops@example.com < secret_file` should be rejected via `<` detection."""
    _write_drill_timer_and_service(
        tmp_path,
        "/usr/bin/mail -s drill ops@example.com < /home/user/.taskhub/approvals/id.signed",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "framework_intake_violation_drill_timer_alert_only_shell_composition" in output


# ---- 6. R2 F-PR70-T03-R2-003 adopt: path spoofing ----
def test_path_spoofing_tmp_rejected(tmp_path: Path) -> None:
    """`/tmp/slack-cli ...` should be rejected (untrusted absolute path)."""
    _write_drill_timer_and_service(
        tmp_path,
        "/tmp/slack-cli chat send --channel ops drill",  # noqa: S108 (intentional path-spoofing test literal)
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "framework_intake_violation_drill_timer_alert_only_path_spoofing" in output


def test_cron_path_env_rejected(tmp_path: Path) -> None:
    """cron `PATH=./ops/bin\\n...slack-cli...` PATH spoofing env line rejected."""
    cron_d = tmp_path / "etc" / "cron.d"
    cron_d.mkdir(parents=True)
    (cron_d / "drill-cron").write_text(
        "PATH=/usr/bin:/tmp/evil\n0 9 1 1,7 * root /usr/bin/slack-cli chat send drill\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert (
        "framework_intake_violation_drill_timer_alert_only_path_spoofing_env_line" in output
    )


# ---- 7. R1 F-005 adopt: shell composition bypass via head match ----
@pytest.mark.parametrize(
    "exec_cmd,expected_label",
    [
        ('/usr/bin/echo "Drill due at $(date)"', "metacharacter_or_composition"),
        ("/usr/bin/echo Drill && /tmp/payload", "metacharacter_or_composition"),
        ("/usr/bin/echo Drill | /tmp/payload", "metacharacter_or_composition"),
        ("/usr/bin/echo Drill > /var/log/drill.log", "metacharacter_or_composition"),
        ("/usr/bin/echo Drill ; /tmp/payload", "metacharacter_or_composition"),
    ],
    ids=["cmdsub", "and", "pipe", "redirect_out", "semicolon"],
)
def test_shell_composition_bypass_rejected(
    tmp_path: Path, exec_cmd: str, expected_label: str
) -> None:
    _write_drill_timer_and_service(tmp_path, exec_cmd)
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "framework_intake_violation_drill_timer_alert_only_shell_composition" in output
    assert expected_label in output


# ---- 8. R1 F-003 adopt: paired .service missing ----
def test_timer_without_paired_service_rejected(tmp_path: Path) -> None:
    """Orphan .timer (paired .service missing) should emit
    `framework_intake_violation_drill_timer_paired_service_missing`."""
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "taskhub-drill-alert.timer").write_text(
        "[Unit]\nDescription=orphan\n\n[Timer]\nOnCalendar=*-01,07-01 09:00:00\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "framework_intake_violation_drill_timer_paired_service_missing" in output


# ---- 9. R1 F-004 adopt: ExecStartPre destructive ----
def test_systemd_exec_start_pre_destructive_rejected(tmp_path: Path) -> None:
    """`ExecStartPre=/usr/bin/rm -rf /tmp/foo` should be detected (not only ExecStart=)."""
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir(parents=True)
    timer = deploy_dir / "taskhub-drill-alert.timer"
    service = deploy_dir / "taskhub-drill-alert.service"
    timer.write_text(
        "[Unit]\nDescription=drill\n\n[Timer]\nOnCalendar=*-01,07-01 09:00:00\n"
        "Unit=taskhub-drill-alert.service\n",
        encoding="utf-8",
    )
    service.write_text(
        "[Unit]\nDescription=drill\n\n[Service]\nType=oneshot\n"
        "ExecStartPre=/bin/rm -rf /var/log/taskhub\n"
        "ExecStart=/usr/bin/notify-send drill\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "directive=ExecStartPre" in output
    assert "rm_destructive" in output


# ---- 10. macro entry (@daily) ----
def test_cron_macro_taskhub_restore_rejected(tmp_path: Path) -> None:
    cron_d = tmp_path / "etc" / "cron.d"
    cron_d.mkdir(parents=True)
    (cron_d / "drill-cron").write_text(
        "@daily root /usr/local/bin/taskhub age-rotate\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "taskhub_destructive_subcommand" in output


# ---- 11. cron env MAILTO (allowed env line) ----
def test_cron_mailto_env_line_passes(tmp_path: Path) -> None:
    """`MAILTO=ops@example.com` does not trigger path-spoofing (only PATH/SHELL/BASH_ENV do)."""
    cron_d = tmp_path / "etc" / "cron.d"
    cron_d.mkdir(parents=True)
    (cron_d / "drill-cron").write_text(
        "MAILTO=ops@example.com\n0 9 1 1,7 * root /usr/bin/notify-send drill\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 0, f"expected pass, got exit={exit_code} output={output}"
