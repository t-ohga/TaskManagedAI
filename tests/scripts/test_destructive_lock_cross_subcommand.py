"""SP022-T08 carry-over: destructive_lock cross-subcommand 拡張 tests.

migrate / freeze / thaw subcommand が backup と同 destructive_lock pattern で
mutual exclusion を実現することを確認。

既存 backup pattern (PR #80 Phase 5) と同 contract:
- destructive_lock 取得失敗時は ERROR + return 2
- 並列実行は busy で reject
- skeleton mode は lock release 後正常終了 (return 1)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

# 遅延 import for destructive_lock helpers
from scripts.taskhub_destructive_lock import acquire_destructive_lock


def test_acquire_destructive_lock_migrate_acquires_successfully(tmp_path: Path) -> None:
    """SP022-T08 拡張: migrate 経路で destructive_lock を取得可能."""
    lock_dir = tmp_path / "locks"
    # destructive_lock requires 0o700 mode (defense-in-depth、multi-user host info leak 防止)
    lock_dir.mkdir(mode=0o700)
    with patch.dict("os.environ", {"TASKHUB_LOCK_DIR": str(lock_dir)}):
        with acquire_destructive_lock("migrate", None) as (acquired, reason, blocker):
            assert acquired is True
            assert blocker is None
            assert reason == "destructive_lock_acquired"


def test_acquire_destructive_lock_freeze_acquires_successfully(tmp_path: Path) -> None:
    """SP022-T08 拡張: freeze 経路で destructive_lock を取得可能."""
    lock_dir = tmp_path / "locks"
    # destructive_lock requires 0o700 mode (defense-in-depth、multi-user host info leak 防止)
    lock_dir.mkdir(mode=0o700)
    with patch.dict("os.environ", {"TASKHUB_LOCK_DIR": str(lock_dir)}):
        with acquire_destructive_lock("freeze", None) as (acquired, _reason, blocker):
            assert acquired is True
            assert blocker is None


def test_acquire_destructive_lock_thaw_acquires_successfully(tmp_path: Path) -> None:
    """SP022-T08 拡張: thaw 経路で destructive_lock を取得可能."""
    lock_dir = tmp_path / "locks"
    # destructive_lock requires 0o700 mode (defense-in-depth、multi-user host info leak 防止)
    lock_dir.mkdir(mode=0o700)
    with patch.dict("os.environ", {"TASKHUB_LOCK_DIR": str(lock_dir)}):
        with acquire_destructive_lock("thaw", None) as (acquired, _reason, blocker):
            assert acquired is True
            assert blocker is None


def test_concurrent_lock_attempts_second_subcommand_busy(tmp_path: Path) -> None:
    """SP022-T08 拡張: 並列 backup / migrate 実行で 2 番目は busy reject (mutual exclusion).

    backup と migrate / freeze / thaw 全てが同 destructive_lock pattern を使うため、
    どの組合せでも同時実行は busy reject されることを確認。
    """
    lock_dir = tmp_path / "locks"
    # destructive_lock requires 0o700 mode (defense-in-depth、multi-user host info leak 防止)
    lock_dir.mkdir(mode=0o700)
    with patch.dict("os.environ", {"TASKHUB_LOCK_DIR": str(lock_dir)}):
        with acquire_destructive_lock("backup", None) as (first_acquired, _r1, _b1):
            assert first_acquired is True
            # 2 番目の migrate は busy
            with acquire_destructive_lock("migrate", None) as (
                second_acquired, second_reason, second_blocker,
            ):
                assert second_acquired is False
                assert second_reason == "destructive_lock_busy"
                assert second_blocker is not None  # holder pid info


def test_lock_released_after_first_subcommand_allows_second(tmp_path: Path) -> None:
    """SP022-T08 拡張: 1 番目が release 後、2 番目が取得可能 (re-entrant via release)."""
    lock_dir = tmp_path / "locks"
    # destructive_lock requires 0o700 mode (defense-in-depth、multi-user host info leak 防止)
    lock_dir.mkdir(mode=0o700)
    with patch.dict("os.environ", {"TASKHUB_LOCK_DIR": str(lock_dir)}):
        # 1st: freeze acquire + release
        with acquire_destructive_lock("freeze", None) as (acquired_1, _r1, _b1):
            assert acquired_1 is True
        # 2nd: thaw can acquire after release
        with acquire_destructive_lock("thaw", None) as (acquired_2, _r2, blocker_2):
            assert acquired_2 is True
            assert blocker_2 is None


@pytest.mark.parametrize("operation", ["backup", "migrate", "freeze", "thaw"])
def test_all_4_destructive_operations_acquire_consistently(
    tmp_path: Path, operation: str
) -> None:
    """SP022-T08 拡張: backup + migrate + freeze + thaw 全 4 operation で同 pattern.

    parameterized で 4 operations を個別 acquire、全件成功を確認 (cross-subcommand
    consistency contract)。
    """
    lock_dir = tmp_path / "locks"
    # destructive_lock requires 0o700 mode (defense-in-depth、multi-user host info leak 防止)
    lock_dir.mkdir(mode=0o700)
    with patch.dict("os.environ", {"TASKHUB_LOCK_DIR": str(lock_dir)}):
        with acquire_destructive_lock(operation, None) as (acquired, reason, blocker):
            assert acquired is True
            assert blocker is None
            assert reason == "destructive_lock_acquired"
