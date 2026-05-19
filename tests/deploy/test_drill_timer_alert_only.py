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
    # PR71 R4-005 (P1) adopt: osascript -e must be quoted as a single `display notification ...`
    # statement; using shlex-friendly literal here.
    _write_drill_timer_and_service(
        tmp_path,
        '/usr/bin/osascript -e "display notification \\"Drill due\\" with title \\"TaskManagedAI\\""',
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 0, f"expected pass, got exit={exit_code} output={output}"


# PR71 R4-005 (P1): osascript with `do shell script` (arbitrary cmd) must reject
def test_osascript_do_shell_script_rejected(tmp_path: Path) -> None:
    """`osascript -e 'do shell script "..."'` enables arbitrary cmd → must reject."""
    _write_drill_timer_and_service(
        tmp_path,
        '/usr/bin/osascript -e "do shell script \\"echo evil\\""',
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "osascript_payload_unsafe" in output


# PR71 R4-001: systemd Exec prefix `@` strip
def test_exec_prefix_at_pass(tmp_path: Path) -> None:
    """`ExecStart=@/usr/bin/notify-send notify-send drill` (special @ prefix) should pass."""
    _write_drill_timer_and_service(tmp_path, "@/usr/bin/notify-send notify-send drill")
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 0, f"expected pass, got exit={exit_code} output={output}"


# PR71 R4-002 (P1): drop-in override .conf scanned
def test_dropin_override_destructive_rejected(tmp_path: Path) -> None:
    """drop-in override `taskhub-drill-alert.service.d/override.conf` with destructive ExecStart rejected."""
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "taskhub-drill-alert.timer").write_text(
        "[Unit]\nDescription=drill\n\n[Timer]\nOnCalendar=*-01,07-01 09:00:00\n"
        "Unit=taskhub-drill-alert.service\n",
        encoding="utf-8",
    )
    (deploy_dir / "taskhub-drill-alert.service").write_text(
        "[Service]\nType=oneshot\nExecStart=/usr/bin/notify-send drill\n",
        encoding="utf-8",
    )
    dropin_dir = deploy_dir / "taskhub-drill-alert.service.d"
    dropin_dir.mkdir(parents=True)
    (dropin_dir / "override.conf").write_text(
        "[Service]\nExecStart=\nExecStart=/usr/local/bin/taskhub migrate --target vps\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "taskhub_destructive_subcommand" in output


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


# ---- new: PR71 R1-007 (P1) path traversal bypass ----
def test_path_traversal_via_dotdot_rejected(tmp_path: Path) -> None:
    """`/usr/local/bin/../../tmp/slack-cli` normalizes to `/tmp/slack-cli`, must reject."""
    _write_drill_timer_and_service(
        tmp_path,
        "/usr/local/bin/../../tmp/slack-cli chat send drill",  # noqa: S108
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "framework_intake_violation_drill_timer_alert_only_path_spoofing" in output


# ---- new: PR71 R1-001 non-drill service excluded from standalone scan ----
def test_non_drill_service_under_deploy_excluded(tmp_path: Path) -> None:
    """`deploy/production-app.service` (non-drill name) should NOT trigger scan."""
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "production-app.service").write_text(
        "[Service]\nExecStart=/usr/bin/docker compose up -d\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 0, f"expected pass (non-drill service excluded), got exit={exit_code} output={output}"


# ---- new: PR71 R1-002 cron.d macro user field stripping ----
def test_cron_d_macro_user_field_stripped_pass(tmp_path: Path) -> None:
    """cron.d `@daily root /usr/bin/notify-send drill` should pass (user stripped, allowlist head match)."""
    cron_d = tmp_path / "etc" / "cron.d"
    cron_d.mkdir(parents=True)
    (cron_d / "drill-cron").write_text(
        "@daily root /usr/bin/notify-send drill\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 0, f"expected pass, got exit={exit_code} output={output}"


# ---- PR71 R2-002 (P1): ExecSearchPath= spoofing ----
def test_exec_search_path_rejected(tmp_path: Path) -> None:
    """`ExecSearchPath=/tmp/evil` enables bare-cmd spoofing → must reject."""
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "taskhub-drill-alert.timer").write_text(
        "[Unit]\nDescription=drill\n\n[Timer]\nOnCalendar=*-01,07-01 09:00:00\n"
        "Unit=taskhub-drill-alert.service\n",
        encoding="utf-8",
    )
    (deploy_dir / "taskhub-drill-alert.service").write_text(
        "[Unit]\nDescription=drill\n\n[Service]\nType=oneshot\n"
        "ExecSearchPath=/tmp/evil\n"
        "ExecStart=slack-cli chat send drill\n",  # noqa: S108
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "framework_intake_violation_drill_timer_alert_only_exec_search_path" in output


# ---- PR71 R2-005: systemd Exec prefix `-` (ignore-failure) ----
def test_exec_prefix_dash_pass(tmp_path: Path) -> None:
    """`ExecStart=-/usr/bin/notify-send drill` (ignore-failure prefix) should pass after strip."""
    _write_drill_timer_and_service(tmp_path, "-/usr/bin/notify-send drill")
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 0, f"expected pass, got exit={exit_code} output={output}"


# ---- PR71 R2-003: shell expansion `~` `*` `?` ----
def test_tilde_expansion_rejected(tmp_path: Path) -> None:
    """`mail -A ~/.taskhub/approvals/*.signed` should be rejected (tilde + glob expansion)."""
    cron_d = tmp_path / "etc" / "cron.d"
    cron_d.mkdir(parents=True)
    (cron_d / "drill-cron").write_text(
        "0 9 1 1,7 * root /usr/bin/mail -A ~/.taskhub/approvals/drill.signed ops@example.com\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "framework_intake_violation_drill_timer_alert_only_shell_composition" in output


def test_glob_expansion_rejected(tmp_path: Path) -> None:
    """`mail -A ~/.taskhub/approvals/*.signed` glob `*` expansion rejected."""
    cron_d = tmp_path / "etc" / "cron.d"
    cron_d.mkdir(parents=True)
    (cron_d / "drill-cron").write_text(
        "0 9 1 1,7 * root /usr/bin/mail -A /var/taskhub/drill-*.log ops@example.com\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "framework_intake_violation_drill_timer_alert_only_shell_composition" in output


# ---- PR71 R2-001: diff-gate non-drill service excluded ----
def test_diff_gate_non_drill_service_excluded(tmp_path: Path) -> None:
    """In baseline-scan (which excludes non-drill), non-drill `.service` not scanned."""
    # baseline-scan も diff-gate も同 filter (`*drill*`)
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "production-app.service").write_text(
        "[Service]\nExecStart=/usr/bin/docker compose up -d production\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 0, f"non-drill service excluded; got exit={exit_code} output={output}"


# ---- PR71 R3-003 (P1): adjacent `&` without spaces ----
def test_adjacent_ampersand_rejected(tmp_path: Path) -> None:
    """`echo drill&/tmp/payload` (no space around `&`) should be rejected (cron /bin/sh control op)."""
    _write_drill_timer_and_service(tmp_path, "/usr/bin/echo drill&/tmp/payload")  # noqa: S108
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "framework_intake_violation_drill_timer_alert_only_shell_composition" in output


# ---- PR71 R3-002 (P1): diff-gate non-drill paired service referenced from drill timer ----
def test_diff_gate_paired_service_non_drill_name(tmp_path: Path) -> None:
    """When a drill timer references a non-drill named service, diff-gate must include it."""
    # Use baseline-scan to verify behavior (filename `send-alert.service` referenced from
    # `drill-alert.timer` via `[Timer] Unit=send-alert.service`).
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "taskhub-drill-alert.timer").write_text(
        "[Unit]\nDescription=drill\n\n[Timer]\nOnCalendar=*-01,07-01 09:00:00\n"
        "Unit=send-alert.service\n",
        encoding="utf-8",
    )
    (deploy_dir / "send-alert.service").write_text(
        "[Unit]\nDescription=alert sender\n\n[Service]\nType=oneshot\n"
        "ExecStart=/usr/local/bin/taskhub migrate --target vps\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    # baseline-scan で paired service 経由 detection 確認
    assert exit_code == 1, f"expected violation, got exit={exit_code} output={output}"
    assert "taskhub_destructive_subcommand" in output


# ---- PR71 R3-001 cron.d 6-field user crontab (`root` user explicit) ----
def test_cron_d_5_field_without_user_rejected(tmp_path: Path) -> None:
    """cron.d entry without user field is `six_field_parse_failed`."""
    cron_d = tmp_path / "etc" / "cron.d"
    cron_d.mkdir(parents=True)
    (cron_d / "drill-cron").write_text(
        "0 9 1 1,7 * /usr/bin/notify-send drill\n",  # missing user field
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    # cron.d entry without explicit user field → six_field_parse_failed violation
    # (PR71 R3-001 adopt: cron.d は 6-field 必須、`root` 等明示推奨 = SOP example で対処済)
    assert (
        "framework_intake_violation_drill_timer_alert_only_cron_parse_failed" in output
        and "six_field_parse_failed" in output
    )


# ---- PR71 R5-002 (P1): osascript embedded `do shell script` ----
def test_osascript_embedded_shell_script_rejected(tmp_path: Path) -> None:
    """`osascript -e 'display notification (do shell script "curl ...")'` rejected."""
    _write_drill_timer_and_service(
        tmp_path,
        '/usr/bin/osascript -e "display notification (do shell script \\"echo evil\\")"',
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "osascript_payload_unsafe" in output


# ---- PR71 R5-003 (P1): Environment=PATH override ----
def test_environment_path_override_rejected(tmp_path: Path) -> None:
    """`Environment=PATH=/tmp/evil` enables PATH spoofing for bare commands → reject."""
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "taskhub-drill-alert.timer").write_text(
        "[Unit]\nDescription=drill\n\n[Timer]\nOnCalendar=*-01,07-01 09:00:00\n"
        "Unit=taskhub-drill-alert.service\n",
        encoding="utf-8",
    )
    (deploy_dir / "taskhub-drill-alert.service").write_text(
        "[Service]\nType=oneshot\n"
        "Environment=PATH=/tmp/evil\n"  # noqa: S108
        "ExecStart=/usr/bin/notify-send drill\n",
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "path_override_env" in output


# ---- PR71 R5-004: cron.d 6-field with missing command ----
def test_cron_d_user_field_only_rejected(tmp_path: Path) -> None:
    """cron.d entry `0 9 1 1,7 * /usr/bin/notify-send` (no command after user) rejected."""
    cron_d = tmp_path / "etc" / "cron.d"
    cron_d.mkdir(parents=True)
    (cron_d / "drill-cron").write_text(
        "0 9 1 1,7 * /usr/bin/notify-send\n",  # 6 fields, no command after user
        encoding="utf-8",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "cron_parse_failed" in output


# ---- PR71 R5-005: mail -A attachment exfiltration ----
def test_mail_attach_flag_rejected(tmp_path: Path) -> None:
    """`mail -A /home/user/.taskhub/approvals/id.signed ops@example.com` reject."""
    _write_drill_timer_and_service(
        tmp_path,
        "/usr/bin/mail -A /home/user/.taskhub/approvals/id.signed -s drill ops@example.com",
    )
    exit_code, output = _run_scanner_baseline(tmp_path)
    assert exit_code == 1
    assert "mail_attachment_forbidden" in output


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
