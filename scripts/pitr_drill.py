#!/usr/bin/env python3
"""PITR drill (Sprint 11.5 batch 3a、BL-0137 + BL-0159b).

PostgreSQL の Point-in-Time Recovery drill を実行する admin script.

3 drill_kinds (ADR-00026 §設計判断 line 65-67):
1. `dev_restore`: local dev DB に base backup を restore
2. `private_staging_restore`: Tailscale staging VPS に rsync + restore
3. `pitr`: point-in-time recovery (任意 timestamp + WAL replay)

CRITICAL invariant trace:
- Actor binding (ADR-00026 §設計判断): cron user `postgres` (base backup) + `root`
  (PITR drill rsync)、admin SSH 経由 manual trigger も同 user 限定
- raw secret 不出力: DATABASE_URL の password を log で redact
- deny-by-default: AI / runner / GitHub Actions runner からの trigger 経路なし

Usage:
    sudo python scripts/pitr_drill.py --kind <dev_restore|private_staging_restore|pitr>
        [--dry-run]
        [--target-timestamp <ISO 8601>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess  # noqa: S404 (admin script、必須)
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

logger = logging.getLogger("pitr_drill")

DrillKind = Literal["dev_restore", "private_staging_restore", "pitr"]
"""3 drill_kinds (ADR-00026 §3 + Sprint 11.5 BL-0159b activation)."""

VALID_DRILL_KINDS: frozenset[str] = frozenset(
    {"dev_restore", "private_staging_restore", "pitr"}
)


@dataclass(frozen=True, slots=True)
class PitrDrillResult:
    """PITR drill execution result."""

    timestamp: str
    drill_kind: DrillKind
    dry_run: bool
    success: bool
    duration_seconds: float
    rpo_hours: float | None
    rto_hours: float | None
    plan_or_log: str
    error_message: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def _redact_database_url(url: str) -> str:
    """`DATABASE_URL` から password を redact (log safe、ADR-00026 §設計判断 raw secret 不出力)."""

    parsed = urlparse(url)
    if parsed.password:
        netloc = f"{parsed.username or 'user'}:***@{parsed.hostname or 'host'}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()
    return url


def _validate_drill_kind(kind: str) -> DrillKind:
    if kind not in VALID_DRILL_KINDS:
        raise ValueError(
            f"invalid drill_kind: {kind!r}, must be one of {sorted(VALID_DRILL_KINDS)}"
        )
    return kind  # type: ignore[return-value]


def _build_pg_basebackup_command(target_dir: Path) -> list[str]:
    """`pg_basebackup` command 配列を構築 (subprocess 直渡し)."""

    return [
        "pg_basebackup",
        "-D",
        str(target_dir),
        "-X",
        "fetch",  # WAL も fetch
        "-P",  # progress report
        "-v",  # verbose
    ]


def _build_dev_restore_plan(backup_dir: Path) -> str:
    """dev_restore plan output (dry-run)."""

    return (
        f"dev_restore plan:\n"
        f"  1. stop docker-compose api/worker (preserve volume)\n"
        f"  2. pg_basebackup to {backup_dir}\n"
        f"  3. restart docker-compose with backup_dir mounted\n"
        f"  4. verify SELECT 1 + critical table row counts"
    )


def _build_staging_restore_plan(backup_dir: Path, tailscale_host: str) -> str:
    """private_staging_restore plan output (dry-run)."""

    return (
        f"private_staging_restore plan:\n"
        f"  1. pg_basebackup to {backup_dir}\n"
        f"  2. tailscale ssh {tailscale_host} 'mkdir -p /var/lib/postgresql/staging_restore'\n"
        f"  3. rsync -az {backup_dir}/ {tailscale_host}:/var/lib/postgresql/staging_restore/\n"
        f"  4. tailscale ssh {tailscale_host} 'systemctl restart postgresql-staging'\n"
        f"  5. verify connection from staging api"
    )


def _build_pitr_plan(backup_dir: Path, target_timestamp: str) -> str:
    """pitr plan output (dry-run、任意 timestamp + WAL replay)."""

    return (
        f"pitr plan:\n"
        f"  1. pg_basebackup to {backup_dir}\n"
        f"  2. create recovery.signal in restore directory\n"
        f"  3. configure postgresql.auto.conf:\n"
        f"     restore_command = 'cp /var/lib/postgresql/wal_archive/%f %p'\n"
        f"     recovery_target_time = '{target_timestamp}'\n"
        f"  4. start postgres + wait for recovery\n"
        f"  5. verify recovery completed at target_timestamp"
    )


async def run_dry_run(
    kind: DrillKind,
    *,
    backup_dir: Path,
    target_timestamp: str | None = None,
    tailscale_host: str = "t-ohga-vps",
) -> str:
    """Drill の plan output を生成 (dry-run mode、実 subprocess spawn なし)."""

    if kind == "dev_restore":
        return _build_dev_restore_plan(backup_dir)
    if kind == "private_staging_restore":
        return _build_staging_restore_plan(backup_dir, tailscale_host)
    if kind == "pitr":
        ts = target_timestamp or "<must specify --target-timestamp>"
        return _build_pitr_plan(backup_dir, ts)
    # 未到達 (kind は VALID_DRILL_KINDS で validate 済)
    raise ValueError(f"unsupported drill_kind: {kind}")  # noqa: TRY003


def _run_subprocess(cmd: list[str], *, capture: bool = True) -> tuple[int, str]:
    """subprocess 実行 (admin script、real-run mode)."""

    try:
        result = subprocess.run(  # noqa: S603 (admin script、shell 経由なし、引数 array 渡し)
            cmd,
            capture_output=capture,
            text=True,
            check=False,
            timeout=3600,
        )
        return result.returncode, (result.stdout + result.stderr if capture else "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


async def run_dev_restore(backup_dir: Path) -> tuple[bool, str]:
    """dev_restore drill の real-run (admin only、`pg_basebackup` spawn)."""

    cmd = _build_pg_basebackup_command(backup_dir)
    code, output = _run_subprocess(cmd)
    return (code == 0, output)


async def run_pitr_drill(
    kind: DrillKind,
    *,
    backup_dir: Path,
    target_timestamp: str | None = None,
    dry_run: bool = True,
    tailscale_host: str = "t-ohga-vps",
) -> PitrDrillResult:
    """PITR drill を実行 (dry-run / real-run、3 drill_kinds 対応)."""

    started_at = datetime.now(tz=UTC)
    timestamp_iso = started_at.isoformat()
    _validate_drill_kind(kind)

    if dry_run:
        # Codex F-PR45-003 P2 adopt: pitr kind は target_timestamp が必須.
        # 未指定で success=True を返すと「実行不可能 drill を pass と誤報告」する.
        if kind == "pitr" and not target_timestamp:
            duration = (datetime.now(tz=UTC) - started_at).total_seconds()
            return PitrDrillResult(
                timestamp=timestamp_iso,
                drill_kind=kind,
                dry_run=True,
                success=False,
                duration_seconds=duration,
                rpo_hours=None,
                rto_hours=None,
                plan_or_log=(
                    "pitr drill_kind requires --target-timestamp (ISO 8601). "
                    "Plan cannot be executed without recovery target."
                ),
                error_message="missing_target_timestamp",
            )

        plan = await run_dry_run(
            kind,
            backup_dir=backup_dir,
            target_timestamp=target_timestamp,
            tailscale_host=tailscale_host,
        )
        duration = (datetime.now(tz=UTC) - started_at).total_seconds()
        return PitrDrillResult(
            timestamp=timestamp_iso,
            drill_kind=kind,
            dry_run=True,
            success=True,
            duration_seconds=duration,
            rpo_hours=None,  # dry-run では measurement なし
            rto_hours=None,
            plan_or_log=plan,
        )

    # real-run: 本 sub-batch では dev_restore のみ supported (staging / pitr は Sprint 12)
    if kind != "dev_restore":
        return PitrDrillResult(
            timestamp=timestamp_iso,
            drill_kind=kind,
            dry_run=False,
            success=False,
            duration_seconds=0.0,
            rpo_hours=None,
            rto_hours=None,
            plan_or_log=(
                f"{kind} real-run is deferred to Sprint 12 BL-0144 host migration drill. "
                f"Use --dry-run for plan output."
            ),
            error_message="deferred_to_sprint12",
        )

    success, log = await run_dev_restore(backup_dir)
    duration = (datetime.now(tz=UTC) - started_at).total_seconds()
    return PitrDrillResult(
        timestamp=timestamp_iso,
        drill_kind=kind,
        dry_run=False,
        success=success,
        duration_seconds=duration,
        rpo_hours=24.0,  # ADR-00026 §設計判断
        rto_hours=4.0,
        plan_or_log=log,
    )


def _main_sync(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger.info("pitr_drill_start: kind=%s dry_run=%s", args.kind, args.dry_run)

    result = asyncio.run(
        run_pitr_drill(
            args.kind,
            backup_dir=Path(args.backup_dir),
            target_timestamp=args.target_timestamp,
            dry_run=args.dry_run,
            tailscale_host=args.tailscale_host,
        )
    )

    print(result.to_json())  # noqa: T201
    return 0 if result.success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="PostgreSQL PITR drill (Sprint 11.5 BL-0159b)")
    parser.add_argument(
        "--kind",
        required=True,
        choices=sorted(VALID_DRILL_KINDS),
        help="drill_kind: dev_restore | private_staging_restore | pitr",
    )
    parser.add_argument(
        "--backup-dir",
        default="/var/lib/postgresql/backups/drill",
        help="backup target directory",
    )
    parser.add_argument(
        "--target-timestamp",
        default=None,
        help="PITR target timestamp (ISO 8601、pitr kind のみ必須)",
    )
    parser.add_argument(
        "--tailscale-host",
        default="t-ohga-vps",
        help="Tailscale hostname for staging restore",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,  # safe default: dry-run
        help="Print plan only (default), no subprocess spawn",
    )
    parser.add_argument(
        "--real-run",
        action="store_false",
        dest="dry_run",
        help="Execute actual pg_basebackup (admin only)",
    )
    args = parser.parse_args()
    return _main_sync(args)


__all__ = [
    "DrillKind",
    "PitrDrillResult",
    "VALID_DRILL_KINDS",
    "_redact_database_url",
    "_validate_drill_kind",
    "main",
    "run_dry_run",
    "run_pitr_drill",
]


if __name__ == "__main__":
    sys.exit(main())
