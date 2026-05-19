"""Drill timer / cron destructive command scanner (ADR-00021 §14.2 #4 PGA-F-013, SP022-T03).

Scans systemd `.timer` / `.service` files and cron entries for ExecStart / command lines.
Allowlist = notification commands (notify-send / osascript / slack-cli / discord-cli / mail /
sendmail / echo / printf / logger). Denylist (defense-in-depth) = destructive commands
(taskhub migrate/restore/age-rotate/backup / docker compose down / pg_* / dropdb / psql DROP /
redis-cli flush / rm -rf / dd / mkfs / kill -9 / systemctl stop / shutdown).

R2 F-PR70-T03-R2-002 + R2-003 adopt: single-char `<` redirect detection + path spoofing checks
(TRUSTED_PATH_PREFIXES + cron PATH/SHELL/BASH_ENV fail-closed).
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

# allowlist: notification command heads (PATH-resolved bare command OR trusted absolute path).
ALLOWLIST_HEADS: frozenset[str] = frozenset(
    {
        "notify-send",
        "osascript",
        "slack-cli",
        "slack",
        "discord-cli",
        "discord",
        "mail",
        "sendmail",
        "echo",
        "printf",
        "logger",
    }
)

# denylist (defense-in-depth, not exhaustive): regex pattern → label
DENYLIST_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\btaskhub\s+(migrate|restore|age-rotate|backup)\b", "taskhub_destructive_subcommand"),
    (r"\bdocker\s+compose\s+(down|stop|kill|rm)\b", "docker_compose_destructive"),
    (r"\bdocker\s+volume\s+(rm|prune)\b", "docker_volume_destructive"),
    (r"\bkubectl\s+(delete|scale)\b", "kubectl_destructive"),
    (r"\bpg_(dump|restore|basebackup|drop)\b", "postgres_direct_operation"),
    (r"\b(dropdb|createdb)\b", "postgres_db_lifecycle"),
    (r"\bpsql\b.*\b(DROP|TRUNCATE|DELETE)\b", "psql_destructive_sql"),
    (r"\bredis-cli\s+(flushall|flushdb)\b", "redis_flush"),
    (r"\brm\s+(-[a-zA-Z]*[rRfF][a-zA-Z]*)", "rm_destructive"),
    (r"\bfind\s+.*-(delete|exec\s+rm)\b", "find_destructive"),
    (r"\bunlink\b", "unlink"),
    (r"\b(dd|mkfs|truncate)(\s|$)", "low_level_destructive"),
    (r"\bkill\s+-9\b", "kill_force"),
    (r"\bpkill\s+-9\b", "pkill_force"),
    (
        r"\bsystemctl\s+(stop|restart|kill|disable|poweroff|reboot)\b",
        "systemctl_control",
    ),
    (r"\b(shutdown|reboot|poweroff|halt)\b", "host_power_destructive"),
)

# R1 F-005 + R2 F-PR70-T03-R2-002 adopt: shell composition detection (input `<` 単独も
# `<+` で 1 個以上 match).
SHELL_COMPOSITION_RE = re.compile(r"(\$\(|`|;|&&|\|\||\||>>?|<+|\s&\s|\s&$)")
SHELL_NEWLINE_RE = re.compile(r"\n")

# R2 F-PR70-T03-R2-003 adopt: trusted absolute path prefixes (allowlist external paths only
# from system bin dirs; reject `/tmp/...`, `~/...`, `./...`, etc.).
TRUSTED_PATH_PREFIXES: tuple[str, ...] = (
    "/usr/bin/",
    "/usr/local/bin/",
    "/bin/",
    "/usr/sbin/",
    "/sbin/",
    "/opt/homebrew/bin/",
    "/opt/local/bin/",
)

# R2 F-PR70-T03-R2-003 adopt: cron env line variables that enable PATH spoofing.
PATH_SPOOFING_ENV_VARS: frozenset[str] = frozenset(
    {
        "PATH",
        "SHELL",
        "BASH_ENV",
        "ENV",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
    }
)

# systemd Exec*= directives to scan (R1 F-004 adopt: cover Pre/Post/Reload/Stop/StopPost,
# not just ExecStart).
SYSTEMD_EXEC_DIRECTIVES: tuple[str, ...] = (
    "ExecStartPre",
    "ExecStart",
    "ExecStartPost",
    "ExecReload",
    "ExecStop",
    "ExecStopPost",
    "ExecCondition",
)
SYSTEMD_EXEC_RE = re.compile(
    r"^\s*(" + "|".join(SYSTEMD_EXEC_DIRECTIVES) + r")\s*=\s*(.+)$",
    re.MULTILINE,
)

# systemd timer `Unit=` directive (paired service resolution).
SYSTEMD_UNIT_RE = re.compile(r"^\s*Unit\s*=\s*(\S+)\s*$", re.MULTILINE)

# cron line patterns.
CRON_MACRO_RE = re.compile(
    r"^\s*(@(?:reboot|yearly|annually|monthly|weekly|daily|midnight|hourly))\s+(.+)$",
    re.MULTILINE,
)
# 5-field user crontab: minute hour day-of-month month day-of-week command
CRON_FIVE_FIELD_RE = re.compile(
    r"^\s*([\S]+\s+){5}(.+)$",
    re.MULTILINE,
)
# 6-field /etc/cron.d: above + user field
CRON_SIX_FIELD_RE = re.compile(
    r"^\s*([\S]+\s+){5}([\w_-]+)\s+(.+)$",
    re.MULTILINE,
)
CRON_ENV_LINE_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*=")

EXCLUDE_DIRS: frozenset[str] = frozenset(
    {".git", ".venv", "node_modules", "__pycache__"}
)


# scope-limited glob patterns (R1 F-007 adopt).
SCAN_TIMER_GLOBS: tuple[str, ...] = (
    "**/*drill*.timer",
    "docs/deploy/**/*.timer",
    "deploy/**/*.timer",
    "ops/**/*.timer",
)
# PR71 R1-001 adopt: limit standalone service scanning to drill-named files only.
# non-drill .service under deploy/ ops/ (e.g., production app service) はpaired timer 経由でのみ scan、
# standalone での scan は drill-named のみ。
SCAN_SERVICE_GLOBS: tuple[str, ...] = (
    "**/*drill*.service",
    "docs/deploy/**/*drill*.service",
    "deploy/**/*drill*.service",
    "ops/**/*drill*.service",
)
SCAN_CRON_GLOBS: tuple[str, ...] = (
    "**/crontab",
    "**/crontabs/**/*",
    "**/cron.d/**/*",
    "etc/cron.d/**/*",
)


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)


def _iter_glob(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for p in root.glob(pattern):
            if _is_excluded(p):
                continue
            if not p.is_file():
                continue
            if p in seen:
                continue
            seen.add(p)
            files.append(p)
    return files


def _read_text_or_none(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _check_shell_composition(cmd_line: str) -> tuple[str | None, str | None]:
    """Return (reason_suffix, label) if shell composition detected, else (None, None)."""
    if SHELL_COMPOSITION_RE.search(cmd_line) or SHELL_NEWLINE_RE.search(cmd_line):
        return ("shell_composition", "metacharacter_or_composition")
    return (None, None)


def _check_denylist(cmd_line: str) -> tuple[str | None, str | None]:
    for pattern, label in DENYLIST_PATTERNS:
        if re.search(pattern, cmd_line):
            return ("destructive_command", label)
    return (None, None)


def _check_path_spoofing(cmd_head: str) -> tuple[str | None, str | None]:
    """If cmd_head contains `/`, must start with a trusted prefix after `..` normalization.

    R2 F-PR70-T03-R2-003 + PR71 R1-007 (P1) adopt: bare `startswith` allowed
    `/usr/local/bin/../../tmp/slack-cli` to pass trusted prefix check via `..` traversal.
    Normalize with `os.path.normpath` before prefix match to reject traversal bypass.
    """
    if "/" not in cmd_head:
        return (None, None)
    # Normalize `..` segments before prefix check (PR71 R1-007 P1 adopt).
    import os.path

    normalized = os.path.normpath(cmd_head)
    if any(normalized.startswith(prefix) for prefix in TRUSTED_PATH_PREFIXES):
        return (None, None)
    return ("path_spoofing", f"untrusted_path={cmd_head[:80]}")


def _check_command(cmd_line: str) -> tuple[str | None, str | None]:
    """Check a single command line against (1) shell composition, (2) denylist, (3) path
    spoofing, (4) allowlist head. Returns (reason_suffix, label) or (None, None) if pass.

    R1 F-005 + R2 F-PR70-T03-R2-002 + R2 F-PR70-T03-R2-003 adopt: priority order matches the
    plan's §4.3 evaluation order.
    """
    # 1. shell composition (highest priority)
    reason, label = _check_shell_composition(cmd_line)
    if reason is not None:
        return (reason, label)
    # 2. denylist (regex-based defense-in-depth)
    reason, label = _check_denylist(cmd_line)
    if reason is not None:
        return (reason, label)
    # 3. parse tokens
    try:
        tokens = shlex.split(cmd_line)
    except ValueError:
        return ("shlex_parse_failed", "shlex_parse_failed")
    if not tokens:
        return ("unknown_command", "empty_command")
    cmd_head = tokens[0]
    # 4. path spoofing (if cmd_head contains `/`)
    reason, label = _check_path_spoofing(cmd_head)
    if reason is not None:
        return (reason, label)
    # 5. allowlist head match (basename for PATH-resolved bare command OR trusted absolute path)
    head_basename = cmd_head.rsplit("/", 1)[-1]
    if head_basename in ALLOWLIST_HEADS:
        return (None, None)
    return ("unknown_command", head_basename)


def check_systemd_files(scan_files: list[Path] | None, root: Path) -> list[str]:
    """Scan systemd .timer / .service files. If scan_files is given, only scan those plus
    paired .service files (resolved via .timer's Unit= directive). Else scope glob.
    """
    violations: list[str] = []
    if scan_files is None:
        timer_files = _iter_glob(root, SCAN_TIMER_GLOBS)
        service_files = _iter_glob(root, SCAN_SERVICE_GLOBS)
    else:
        timer_files = [p for p in scan_files if p.suffix == ".timer" and p.exists()]
        service_files = [p for p in scan_files if p.suffix == ".service" and p.exists()]
        # PR71 R1-005 adopt: diff-gate で deleted `.service` の paired-missing check
        # changed list 内に deleted `.service` (exists() false) があれば、同名 / 関連 `.timer`
        # を repo baseline から探して `timer_files` に load し、paired-service-missing で
        # 必ず violation emit させる。
        deleted_services = [
            p for p in scan_files if p.suffix == ".service" and not p.exists()
        ]
        for deleted in deleted_services:
            candidate_timer = deleted.with_suffix(".timer")
            if candidate_timer.exists() and candidate_timer not in timer_files:
                timer_files.append(candidate_timer)
            # also discover timers referencing the deleted service via [Timer] Unit=
            for timer_path in _iter_glob(root, SCAN_TIMER_GLOBS):
                if timer_path in timer_files:
                    continue
                content = _read_text_or_none(timer_path)
                if content is None:
                    continue
                unit_match = SYSTEMD_UNIT_RE.search(content)
                if unit_match and unit_match.group(1) == deleted.name:
                    timer_files.append(timer_path)
    # R1 F-003 adopt: resolve paired .service for each .timer
    paired_services: set[Path] = set(service_files)
    for tpath in timer_files:
        content = _read_text_or_none(tpath)
        if content is None:
            continue
        unit_match = SYSTEMD_UNIT_RE.search(content)
        if unit_match:
            unit_name = unit_match.group(1)
            paired = tpath.parent / unit_name
        else:
            paired = tpath.with_suffix(".service")
        if paired.exists():
            paired_services.add(paired)
        else:
            # R1 F-003 adopt: fail-closed when paired service missing
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_drill_timer_paired_service_missing "
                f"evidence={tpath}:1 label=missing_paired_service expected={paired}"
            )
    # R1 F-004 adopt: scan all Exec* directives in service files
    for spath in sorted(paired_services):
        content = _read_text_or_none(spath)
        if content is None:
            continue
        for match in SYSTEMD_EXEC_RE.finditer(content):
            directive = match.group(1)
            cmd_line = match.group(2).strip()
            reason, label = _check_command(cmd_line)
            if reason:
                line_num = content[: match.start()].count("\n") + 1
                violations.append(
                    f"VIOLATION reason_code=framework_intake_violation_drill_timer_alert_only_{reason} "
                    f"evidence={spath}:{line_num} directive={directive} label={label} "
                    f"command={cmd_line[:80]}"
                )
    return violations


def check_cron_files(scan_files: list[Path] | None, root: Path) -> list[str]:
    """Scan cron files. R1 F-008 + R2 F-PR70-T03-R2-003 adopt: robust parser + PATH/SHELL/
    BASH_ENV env line fail-closed.
    """
    violations: list[str] = []
    if scan_files is None:
        cron_files = _iter_glob(root, SCAN_CRON_GLOBS)
    else:
        cron_files = [
            p
            for p in scan_files
            if (p.name == "crontab" or "crontabs" in p.parts or "cron.d" in p.parts)
            and p.is_file()
        ]
    for path in cron_files:
        content = _read_text_or_none(path)
        if content is None:
            continue
        is_etc_crond = "cron.d" in path.parts
        for lineno_minus1, raw_line in enumerate(content.splitlines()):
            line = raw_line.strip()
            line_num = lineno_minus1 + 1
            if not line or line.startswith("#"):
                continue
            # R2 F-PR70-T03-R2-003 adopt: env line PATH/SHELL/BASH_ENV fail-closed
            env_match = CRON_ENV_LINE_RE.match(raw_line)
            if env_match:
                var_name = env_match.group(1)
                if var_name in PATH_SPOOFING_ENV_VARS:
                    violations.append(
                        f"VIOLATION reason_code=framework_intake_violation_drill_timer_alert_only_path_spoofing_env_line "
                        f"evidence={path}:{line_num} label=cron_env_var={var_name} "
                        f"line={raw_line[:80]}"
                    )
                # other env (MAILTO, CRON_TZ, etc.) pass
                continue
            # macro entry (@daily / @hourly / ...)
            macro_match = CRON_MACRO_RE.match(raw_line)
            if macro_match:
                rest = macro_match.group(2).split("%", 1)[0].strip()
                # PR71 R1-002 adopt: cron.d uses system-crontab form `@daily <user> <cmd>`,
                # so strip the leading user field before _check_command.
                if is_etc_crond:
                    parts = rest.split(None, 1)
                    if len(parts) == 2:
                        cmd = parts[1].strip()
                    else:
                        violations.append(
                            f"VIOLATION reason_code=framework_intake_violation_drill_timer_alert_only_cron_parse_failed "
                            f"evidence={path}:{line_num} label=macro_user_field_missing line={raw_line[:80]}"
                        )
                        continue
                else:
                    cmd = rest
                reason, label = _check_command(cmd)
                if reason:
                    violations.append(
                        f"VIOLATION reason_code=framework_intake_violation_drill_timer_alert_only_{reason} "
                        f"evidence={path}:{line_num} macro={macro_match.group(1)} label={label} "
                        f"command={cmd[:80]}"
                    )
                continue
            # 5-field or 6-field
            tokens_count = len(raw_line.split(None, 6))
            if is_etc_crond and tokens_count >= 7:
                # 6-field: parse 5 schedule fields + user + command
                six = CRON_SIX_FIELD_RE.match(raw_line)
                if six:
                    cmd = six.group(3).split("%", 1)[0].strip()
                else:
                    violations.append(
                        f"VIOLATION reason_code=framework_intake_violation_drill_timer_alert_only_cron_parse_failed "
                        f"evidence={path}:{line_num} label=six_field_parse_failed line={raw_line[:80]}"
                    )
                    continue
            elif tokens_count >= 6:
                # 5-field user crontab
                five = CRON_FIVE_FIELD_RE.match(raw_line)
                if five:
                    cmd = five.group(2).split("%", 1)[0].strip()
                else:
                    violations.append(
                        f"VIOLATION reason_code=framework_intake_violation_drill_timer_alert_only_cron_parse_failed "
                        f"evidence={path}:{line_num} label=five_field_parse_failed line={raw_line[:80]}"
                    )
                    continue
            else:
                violations.append(
                    f"VIOLATION reason_code=framework_intake_violation_drill_timer_alert_only_cron_parse_failed "
                    f"evidence={path}:{line_num} label=insufficient_fields line={raw_line[:80]}"
                )
                continue
            reason, label = _check_command(cmd)
            if reason:
                violations.append(
                    f"VIOLATION reason_code=framework_intake_violation_drill_timer_alert_only_{reason} "
                    f"evidence={path}:{line_num} label={label} command={cmd[:80]}"
                )
    return violations


def _load_paths_from_file(path_str: str) -> list[Path]:
    """R2 F-PR70-T03-R2-001 adopt: read NUL-separated path list from a file."""
    data = Path(path_str).read_bytes()
    items = [b for b in data.split(b"\0") if b]
    return [Path(b.decode("utf-8", errors="strict")) for b in items]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["diff-gate", "baseline-scan"],
        required=True,
    )
    parser.add_argument(
        "--paths-from-file",
        help=(
            "NUL-separated path list file (R2 F-PR70-T03-R2-001: bash command "
            "substitution drops NUL bytes, so paths must be passed via a temp file)."
        ),
    )
    args = parser.parse_args()

    root = Path(".")
    scan_files: list[Path] | None = None
    if args.mode == "diff-gate":
        if not args.paths_from_file:
            print(
                "ERROR: --paths-from-file=<path> required in diff-gate mode",
                file=sys.stderr,
            )
            return 2
        scan_files = _load_paths_from_file(args.paths_from_file)

    try:
        violations = check_systemd_files(scan_files, root) + check_cron_files(
            scan_files, root
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR scanner failed: {exc}", file=sys.stderr)
        return 2

    for line in violations:
        print(line)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
