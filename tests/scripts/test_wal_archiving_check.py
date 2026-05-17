"""Sprint 11.5 batch 3a (BL-0137): wal_archiving_check.py logic tests.

DB integration なし: LSN parse + archive lag computation + URL redact のみ unit test.
actual DB connection は Sprint 12 host migration drill で integration verify.
"""

from __future__ import annotations

import pytest

from scripts.wal_archiving_check import (
    WalArchivingReport,
    _redact_database_url,
    compute_archive_lag_bytes,
)


def test_redact_database_url_with_password() -> None:
    """password を `***` で mask."""

    url = "postgresql://user:secret123@host:5432/db"
    redacted = _redact_database_url(url)
    assert "secret123" not in redacted
    assert "***" in redacted
    assert "user" in redacted
    assert "host" in redacted


def test_redact_database_url_without_password() -> None:
    """password 不在の場合 unchanged."""

    url = "postgresql://user@host:5432/db"
    redacted = _redact_database_url(url)
    assert redacted == url


def test_redact_database_url_asyncpg_scheme() -> None:
    """`postgresql+asyncpg://` scheme も redact."""

    url = "postgresql+asyncpg://user:pw@host:5432/db"
    redacted = _redact_database_url(url)
    assert "pw" not in redacted
    assert "***" in redacted


def test_compute_archive_lag_bytes_zero_when_aligned() -> None:
    """current LSN と last_archived WAL filename が一致なら lag = 0."""

    current = "0/3000000"  # log_seg=3 → 3 << 24 = 0x3000000
    # WAL filename: 0x00000001 (timeline) 0x00000000 (log hi) 0x00000003 (log seg)
    last_archived = "000000010000000000000003"
    lag = compute_archive_lag_bytes(current, last_archived)
    assert lag == 0


def test_compute_archive_lag_bytes_positive_when_behind() -> None:
    """current LSN > last_archived → 正の lag."""

    current = "0/5000000"
    last_archived = "000000010000000000000003"  # → 0x3000000
    lag = compute_archive_lag_bytes(current, last_archived)
    assert lag > 0
    assert lag == 0x5000000 - 0x3000000  # 32 MB


def test_compute_archive_lag_bytes_when_empty_archive() -> None:
    """last_archived が空 (archive 未起動) → current LSN そのまま."""

    current = "0/3000000"
    lag = compute_archive_lag_bytes(current, "")
    assert lag == 0x3000000


def test_compute_archive_lag_bytes_invalid_lsn() -> None:
    """LSN format error → ValueError."""

    with pytest.raises(ValueError, match="invalid LSN"):
        compute_archive_lag_bytes("invalid", "000000010000000000000003")


def test_compute_archive_lag_bytes_invalid_wal_filename() -> None:
    """WAL filename format error → ValueError."""

    with pytest.raises(ValueError, match="invalid WAL filename"):
        compute_archive_lag_bytes("0/3000000", "wrong_format")


def test_wal_archiving_report_to_json() -> None:
    """`WalArchivingReport.to_json()` で valid JSON 生成."""

    report = WalArchivingReport(
        timestamp="2026-05-17T00:00:00+00:00",
        healthy=True,
        current_wal_lsn="0/3000000",
        last_archived_wal="000000010000000000000003",
        last_failed_wal=None,
        archive_lag_bytes=0,
        archive_command_configured=True,
        archive_mode_on=True,
    )
    import json
    parsed = json.loads(report.to_json())
    assert parsed["healthy"] is True
    assert parsed["archive_lag_bytes"] == 0
    assert parsed["last_failed_wal"] is None
    assert parsed["error_message"] is None


def test_wal_archiving_report_with_error() -> None:
    """exception 時の report (healthy=False + error_message)."""

    report = WalArchivingReport(
        timestamp="2026-05-17T00:00:00+00:00",
        healthy=False,
        current_wal_lsn=None,
        last_archived_wal=None,
        last_failed_wal=None,
        archive_lag_bytes=None,
        archive_command_configured=False,
        archive_mode_on=False,
        error_message="ConnectionRefusedError",
    )
    assert report.healthy is False
    assert report.error_message == "ConnectionRefusedError"


def test_compute_archive_lag_bytes_log_field_reflected() -> None:
    """Codex F-PR45-001 P1 adopt: WAL filename の middle log field を反映.

    旧 bug: log_id を無視 → 4GB 超で永久 unhealthy.
    Fix: LSN = (log_id << 32) | (seg << 24).
    """

    # WAL filename: timeline=1, log_id=1, seg=0 → LSN 1/00000000 (4 GB)
    # current LSN も 1/00000000 → lag=0 (aligned).
    current = "1/00000000"
    last_archived = "000000010000000100000000"
    lag = compute_archive_lag_bytes(current, last_archived)
    assert lag == 0, f"log_field reflection bug: expected 0, got {lag}"


def test_compute_archive_lag_bytes_log_field_advanced() -> None:
    """log_id=2、seg=0 → LSN 2/00000000 (8 GB)、lag verification."""

    current = "2/00000000"
    last_archived = "000000010000000200000000"
    lag = compute_archive_lag_bytes(current, last_archived)
    assert lag == 0


def test_compute_archive_lag_bytes_across_log_boundary() -> None:
    """current LSN > last_archived LSN with log boundary."""

    # last_archived: log=1, seg=0 → LSN 1/00000000
    # current: log=1, seg=1 → LSN 1/01000000
    # lag = 1 << 24 = 16 MB
    current = "1/01000000"
    last_archived = "000000010000000100000000"
    lag = compute_archive_lag_bytes(current, last_archived)
    assert lag == 0x01000000  # 16 MB
