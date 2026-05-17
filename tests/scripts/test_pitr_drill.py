"""Sprint 11.5 batch 3a (BL-0137 + BL-0159b): pitr_drill.py logic tests.

DB / subprocess 不要、dry-run plan output + drill_kind validation + URL redact.
actual `pg_basebackup` / restore は Sprint 12 host migration drill.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.pitr_drill import (
    VALID_DRILL_KINDS,
    PitrDrillResult,
    _redact_database_url,
    _validate_drill_kind,
    run_dry_run,
    run_pitr_drill,
)


def test_valid_drill_kinds_set() -> None:
    """3 drill_kinds (ADR-00026 §3、Sprint 11.5 BL-0159b activation)."""

    assert VALID_DRILL_KINDS == frozenset(
        {"dev_restore", "private_staging_restore", "pitr"}
    )


@pytest.mark.parametrize("kind", ["dev_restore", "private_staging_restore", "pitr"])
def test_validate_drill_kind_accepts_valid(kind: str) -> None:
    assert _validate_drill_kind(kind) == kind


def test_validate_drill_kind_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="invalid drill_kind"):
        _validate_drill_kind("bogus")


def test_redact_database_url_strips_password() -> None:
    url = "postgresql://user:secret@host:5432/db"
    redacted = _redact_database_url(url)
    assert "secret" not in redacted
    assert "***" in redacted


@pytest.mark.asyncio
async def test_run_dry_run_dev_restore_plan_format(tmp_path: Path) -> None:
    backup_dir = tmp_path / "test_backup"
    plan = await run_dry_run("dev_restore", backup_dir=backup_dir)
    assert "dev_restore plan" in plan
    assert str(backup_dir) in plan
    assert "pg_basebackup" in plan


@pytest.mark.asyncio
async def test_run_dry_run_private_staging_restore_plan_format(tmp_path: Path) -> None:
    backup_dir = tmp_path / "test_backup"
    plan = await run_dry_run(
        "private_staging_restore",
        backup_dir=backup_dir,
        tailscale_host="t-ohga-vps",
    )
    assert "private_staging_restore plan" in plan
    assert "tailscale ssh t-ohga-vps" in plan
    assert "rsync" in plan


@pytest.mark.asyncio
async def test_run_dry_run_pitr_plan_with_target_timestamp(tmp_path: Path) -> None:
    backup_dir = tmp_path / "test_backup"
    plan = await run_dry_run(
        "pitr", backup_dir=backup_dir, target_timestamp="2026-05-17T12:00:00+00:00"
    )
    assert "pitr plan" in plan
    assert "recovery_target_time" in plan
    assert "2026-05-17T12:00:00+00:00" in plan


@pytest.mark.asyncio
async def test_run_pitr_drill_dry_run_dev_restore_success(tmp_path: Path) -> None:
    """dry-run mode は subprocess spawn せず plan output、success=True."""

    backup_dir = tmp_path / "test_backup"
    result = await run_pitr_drill("dev_restore", backup_dir=backup_dir, dry_run=True)
    assert result.dry_run is True
    assert result.success is True
    assert result.drill_kind == "dev_restore"
    assert "dev_restore plan" in result.plan_or_log
    # dry-run では measurement なし
    assert result.rpo_hours is None
    assert result.rto_hours is None


@pytest.mark.asyncio
async def test_run_pitr_drill_real_run_defers_staging(tmp_path: Path) -> None:
    """real-run mode は dev_restore のみ supported、他は Sprint 12 へ defer."""

    backup_dir = tmp_path / "test_backup"
    result = await run_pitr_drill(
        "private_staging_restore", backup_dir=backup_dir, dry_run=False
    )
    assert result.dry_run is False
    assert result.success is False
    assert result.error_message == "deferred_to_sprint12"
    assert "Sprint 12 BL-0144" in result.plan_or_log


@pytest.mark.asyncio
async def test_run_pitr_drill_real_run_defers_pitr(tmp_path: Path) -> None:
    """pitr real-run も Sprint 12 へ defer."""

    backup_dir = tmp_path / "test_backup"
    result = await run_pitr_drill(
        "pitr",
        backup_dir=backup_dir,
        target_timestamp="2026-05-17T12:00:00+00:00",
        dry_run=False,
    )
    assert result.success is False
    assert result.error_message == "deferred_to_sprint12"


@pytest.mark.asyncio
async def test_pitr_dry_run_without_target_timestamp_fails(tmp_path: Path) -> None:
    """Codex F-PR45-003 P2 adopt: pitr dry-run で `--target-timestamp` 未指定は failure.

    旧 bug: placeholder 文字列で success=True 返し、実行不可能 drill を pass 報告.
    """

    backup_dir = tmp_path / "test_backup"
    result = await run_pitr_drill(
        "pitr",
        backup_dir=backup_dir,
        target_timestamp=None,  # 未指定
        dry_run=True,
    )
    assert result.success is False
    assert result.error_message == "missing_target_timestamp"
    assert result.drill_kind == "pitr"
    assert "requires --target-timestamp" in result.plan_or_log


@pytest.mark.asyncio
async def test_pitr_dry_run_with_target_timestamp_succeeds(tmp_path: Path) -> None:
    """pitr kind でも target_timestamp 指定で dry-run success."""

    backup_dir = tmp_path / "test_backup"
    result = await run_pitr_drill(
        "pitr",
        backup_dir=backup_dir,
        target_timestamp="2026-05-17T12:00:00+00:00",
        dry_run=True,
    )
    assert result.success is True
    assert result.error_message is None
    assert "2026-05-17T12:00:00+00:00" in result.plan_or_log


@pytest.mark.asyncio
async def test_non_pitr_dry_run_does_not_require_target_timestamp(tmp_path: Path) -> None:
    """dev_restore / private_staging_restore は target_timestamp 不要."""

    backup_dir = tmp_path / "test_backup"
    s_dev = await run_pitr_drill(
        "dev_restore", backup_dir=backup_dir, target_timestamp=None, dry_run=True
    )
    assert s_dev.success is True
    s_stg = await run_pitr_drill(
        "private_staging_restore",
        backup_dir=backup_dir,
        target_timestamp=None,
        dry_run=True,
    )
    assert s_stg.success is True


def test_pitr_drill_result_to_json() -> None:
    """`PitrDrillResult.to_json()` で valid JSON serialization."""

    result = PitrDrillResult(
        timestamp="2026-05-17T00:00:00+00:00",
        drill_kind="dev_restore",
        dry_run=True,
        success=True,
        duration_seconds=1.5,
        rpo_hours=None,
        rto_hours=None,
        plan_or_log="plan body",
    )
    parsed = json.loads(result.to_json())
    assert parsed["drill_kind"] == "dev_restore"
    assert parsed["dry_run"] is True
    assert parsed["success"] is True
