#!/usr/bin/env python3
"""WAL archiving health check (Sprint 11.5 batch 3a、BL-0137).

PostgreSQL の WAL archiving 状態を確認、archive lag (bytes) と JSON output
を返す. cron 経由で defining 監視 / Prometheus exporter 連携想定.

CRITICAL invariant trace:
- raw secret 不出力: `DATABASE_URL` を env から読むが log に password 含めず
- deny-by-default: production VPS で `postgres` system user として cron 実行、
  admin SSH 経由 manual trigger も `postgres` user 限定

Usage:
    python scripts/wal_archiving_check.py
        --database-url postgresql+asyncpg://user:pass@host:5432/db
        --output json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

logger = logging.getLogger("wal_archiving_check")


@dataclass(frozen=True, slots=True)
class WalArchivingReport:
    """WAL archiving check result (JSON serializable).

    Codex F-PR45-002 P2 adopt: `last_failed_wal` を report に含め、healthy 判定で
    check (archiver failure を即時検出、operator alert 遅延防止).
    """

    timestamp: str
    healthy: bool
    current_wal_lsn: str | None
    last_archived_wal: str | None
    last_failed_wal: str | None
    archive_lag_bytes: int | None
    archive_command_configured: bool
    archive_mode_on: bool
    error_message: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def _redact_database_url(url: str) -> str:
    """`DATABASE_URL` から password を redact (log safe)."""

    parsed = urlparse(url)
    if parsed.password:
        netloc = f"{parsed.username or 'user'}:***@{parsed.hostname or 'host'}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()
    return url


def _parse_lsn(lsn_str: str) -> int:
    """PostgreSQL LSN (`X/Y` hex format) を bytes int に変換."""

    if "/" not in lsn_str:
        raise ValueError(f"invalid LSN format: {lsn_str!r}")
    high, low = lsn_str.split("/", 1)
    return (int(high, 16) << 32) | int(low, 16)


def compute_archive_lag_bytes(current_wal_lsn: str, last_archived_wal: str) -> int:
    """current_wal_lsn と last_archived_wal の lag を bytes で計算.

    WAL filename format (24 hex chars):
    - chars [0:8]: timeline ID (e.g., 00000001)
    - chars [8:16]: log ID (e.g., 00000000) — Codex F-PR45-001 P1 adopt
    - chars [16:24]: segment ID (e.g., 00000003)

    LSN への変換:
        LSN = (log_id << 32) | (segment_id << 24)
    例:
        000000010000000100000000 → log_id=1, seg=0 → LSN 1/00000000 (4 GB)
        000000010000000000000003 → log_id=0, seg=3 → LSN 0/03000000 (48 MB)

    旧バグ: middle log field を無視して seg のみ使用 → 4 GB 超で永久 unhealthy.
    """

    if not last_archived_wal:
        return _parse_lsn(current_wal_lsn)
    if len(last_archived_wal) != 24:
        raise ValueError(f"invalid WAL filename: {last_archived_wal!r}")
    # F-PR45-001 P1 adopt: log_id + seg を両方反映.
    log_id = int(last_archived_wal[8:16], 16)
    log_seg = int(last_archived_wal[16:24], 16)
    last_archived_lsn = (log_id << 32) | (log_seg << 24)
    current_lsn = _parse_lsn(current_wal_lsn)
    return max(0, current_lsn - last_archived_lsn)


async def check_wal_archiving(database_url: str) -> WalArchivingReport:
    """PostgreSQL の WAL archiving 状態を確認.

    `pg_current_wal_lsn()` + `pg_stat_archiver` から情報取得.
    """

    timestamp = datetime.now(tz=UTC).isoformat()
    try:
        # asyncpg を使う (existing dependency)、SQLAlchemy 経由でも可
        import asyncpg  # noqa: PLC0415

        # database_url を asyncpg compatible に変換 (postgresql+asyncpg:// → postgresql://)
        clean_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(clean_url)
        try:
            current_wal_lsn = await conn.fetchval("SELECT pg_current_wal_lsn()::text")
            archive_status = await conn.fetchrow(
                """
                SELECT
                    last_archived_wal,
                    last_failed_wal
                FROM pg_stat_archiver
                """
            )
            archive_mode = await conn.fetchval("SHOW archive_mode")
            archive_command = await conn.fetchval("SHOW archive_command")

            last_archived = archive_status["last_archived_wal"] if archive_status else None
            last_failed = archive_status["last_failed_wal"] if archive_status else None
            archive_mode_on = (str(archive_mode).lower() in ("on", "always"))
            archive_cmd_str = str(archive_command).strip() if archive_command else ""
            archive_command_configured = bool(
                archive_command and archive_cmd_str not in ("", "(disabled)")
            )

            archive_lag_bytes: int | None = None
            if archive_mode_on and current_wal_lsn:
                try:
                    archive_lag_bytes = compute_archive_lag_bytes(
                        str(current_wal_lsn), str(last_archived) if last_archived else ""
                    )
                except ValueError:
                    archive_lag_bytes = None

            # Codex F-PR45-002 P2 adopt: last_failed_wal を healthy 判定に含める.
            # archiver failure を即時検出 (操作員 alert 遅延防止).
            archiver_failed = last_failed is not None and str(last_failed).strip() != ""

            # healthy: archive_mode on + archive_command_configured + lag < 1GB + no recent failure
            healthy = (
                archive_mode_on
                and archive_command_configured
                and not archiver_failed
                and (archive_lag_bytes is None or archive_lag_bytes < 1024 * 1024 * 1024)
            )

            return WalArchivingReport(
                timestamp=timestamp,
                healthy=healthy,
                current_wal_lsn=str(current_wal_lsn) if current_wal_lsn else None,
                last_archived_wal=str(last_archived) if last_archived else None,
                last_failed_wal=str(last_failed) if last_failed else None,
                archive_lag_bytes=archive_lag_bytes,
                archive_command_configured=archive_command_configured,
                archive_mode_on=archive_mode_on,
            )
        finally:
            await conn.close()
    except Exception as exc:  # noqa: BLE001 (cron script、boot-time exception は report 化)
        return WalArchivingReport(
            timestamp=timestamp,
            healthy=False,
            current_wal_lsn=None,
            last_archived_wal=None,
            last_failed_wal=None,
            archive_lag_bytes=None,
            archive_command_configured=False,
            archive_mode_on=False,
            error_message=type(exc).__name__,
        )


def _main_sync(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    redacted_url = _redact_database_url(args.database_url)
    logger.info("wal_archiving_check_start: database=%s", redacted_url)

    report = asyncio.run(check_wal_archiving(args.database_url))

    if args.output == "json":
        print(report.to_json())  # noqa: T201
    else:
        logger.info("healthy=%s lag_bytes=%s", report.healthy, report.archive_lag_bytes)

    return 0 if report.healthy else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="PostgreSQL WAL archiving health check")
    parser.add_argument(
        "--database-url",
        required=True,
        help="PostgreSQL connection URL (postgresql:// or postgresql+asyncpg://)",
    )
    parser.add_argument(
        "--output",
        choices=["json", "text"],
        default="json",
        help="Output format (json for cron-friendly, text for manual run)",
    )
    args = parser.parse_args()
    return _main_sync(args)


__all__ = [
    "WalArchivingReport",
    "_redact_database_url",
    "check_wal_archiving",
    "compute_archive_lag_bytes",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
