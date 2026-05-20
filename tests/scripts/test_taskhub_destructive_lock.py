"""SP022-T02 Phase 4 / R3 F-002 + R4 F-001 + ADV R1 F-002 adopt: destructive lock tests.

Coverage:
- acquire_destructive_lock success path (file create + payload write + release)
- busy / blocker payload (2 process / fork)
- parent dir mode 0o700 enforcement
- TASKHUB_LOCK_DIR env override
- O_NOFOLLOW symlink reject
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from scripts.taskhub_destructive_lock import acquire_destructive_lock


def test_acquire_destructive_lock_success_writes_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("TASKHUB_LOCK_DIR", str(tmp_path / "locks"))
    with acquire_destructive_lock("restore", "drill-2026-07-01-abc12345") as (
        acquired, reason, blocker,
    ):
        assert acquired is True, (reason, blocker)
        assert reason == "destructive_lock_acquired"
        assert blocker is None
        lock_path = tmp_path / "locks" / "destructive-operation.lock"
        assert lock_path.is_file()
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["subcommand"] == "restore"
        assert payload["approval_id"] == "drill-2026-07-01-abc12345"
        assert payload["pid"] == os.getpid()
        assert payload["started_at_utc"].endswith("Z")
        # file mode 0o600
        assert oct(lock_path.stat().st_mode & 0o777) == "0o600"
    # release 後も payload は残る (再取得時 blocker 用)


def test_acquire_destructive_lock_busy_returns_blocker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """別 process が lock 保持中、2 番目の取得は busy reason_code."""
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir(parents=True, mode=0o700)
    lock_path = lock_dir / "destructive-operation.lock"
    # subprocess で lock を直接 fcntl で 5 sec hold する worker を起動
    worker_code = textwrap.dedent(f"""
        import fcntl, json, os, time, sys
        os.umask(0o077)
        fd = os.open({str(lock_path)!r}, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps({{"subcommand": "backup", "approval_id": "drill-blocker-1", "pid": os.getpid(), "started_at_utc": "2026-05-20T10:00:00Z"}}, sort_keys=True).encode())
        os.fsync(fd)
        sys.stdout.write("ready\\n"); sys.stdout.flush()
        time.sleep(5)
    """)
    monkeypatch.setenv("TASKHUB_LOCK_DIR", str(lock_dir))
    p = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", worker_code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        # wait for worker to acquire (ready 出力まで)
        assert p.stdout is not None
        ready_line = p.stdout.readline().decode().strip()
        assert ready_line == "ready", f"worker did not signal ready: {ready_line!r}"
        # small grace
        time.sleep(0.1)
        with acquire_destructive_lock("restore", "drill-second") as (acquired, reason, blocker):
            assert acquired is False, "second acquire should have been busy"
            assert reason == "destructive_lock_busy"
            assert blocker is not None, "blocker payload should be present"
            assert blocker.get("subcommand") == "backup"
    finally:
        p.terminate()
        p.wait(timeout=10)


def test_acquire_destructive_lock_dir_world_readable_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ADV R1 F-002 adopt: parent dir mode 0o755 で reason=dir_permission."""
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir(parents=True, mode=0o755)
    # ensure mode 0o755 (mkdir で mode が umask に応じて変わる場合の補正)
    lock_dir.chmod(0o755)
    monkeypatch.setenv("TASKHUB_LOCK_DIR", str(lock_dir))
    with acquire_destructive_lock("restore", None) as (acquired, reason, _):
        assert acquired is False
        assert reason == "destructive_lock_dir_permission"


def test_acquire_destructive_lock_env_override_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """TASKHUB_LOCK_DIR env が反映される."""
    custom_dir = tmp_path / "custom_locks"
    monkeypatch.setenv("TASKHUB_LOCK_DIR", str(custom_dir))
    with acquire_destructive_lock("freeze", None) as (acquired, reason, _):
        assert acquired is True, reason
        assert (custom_dir / "destructive-operation.lock").is_file()


def test_acquire_destructive_lock_existing_file_mode_enforced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ADV PR F-6 adopt: 既存 lock file が 0o644 でも fchmod 0o600 で強制."""
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir(parents=True, mode=0o700)
    lock_path = lock_dir / "destructive-operation.lock"
    # pre-create with mode 0o644 (multi-user info leak risk)
    lock_path.write_text("", encoding="utf-8")
    lock_path.chmod(0o644)
    monkeypatch.setenv("TASKHUB_LOCK_DIR", str(lock_dir))
    with acquire_destructive_lock("backup", None) as (acquired, reason, _):
        assert acquired is True, reason
        # 取得中に fchmod 0o600 が適用される
        assert oct(lock_path.stat().st_mode & 0o777) == "0o600"


def test_acquire_destructive_lock_symlink_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """O_NOFOLLOW: lock file が symlink で reason=file_permission."""
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir(parents=True, mode=0o700)
    monkeypatch.setenv("TASKHUB_LOCK_DIR", str(lock_dir))
    # symlink 先を準備して lock_path 自体を symlink にする
    target = tmp_path / "target_file"
    target.write_text("decoy", encoding="utf-8")
    lock_path = lock_dir / "destructive-operation.lock"
    os.symlink(str(target), str(lock_path))

    with acquire_destructive_lock("restore", None) as (acquired, reason, _):
        assert acquired is False
        assert reason == "destructive_lock_file_permission"
