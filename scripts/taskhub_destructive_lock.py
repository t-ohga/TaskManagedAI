"""SP022-T02 Phase 4: host-level destructive operation lock.

backup / restore / restore-rollback / migrate / freeze / thaw が同時実行されないことを
`fcntl.flock(LOCK_EX | LOCK_NB)` で保証する advisory lock.

R3 F-002 + R4 F-001 + R5 F-001 + ADV R1 F-002 adopt:
- single-user host (TaskManagedAI operator) 前提、HOME 配下 lock
- `TASKHUB_LOCK_DIR` env override で multi-user host 対応 (e.g., /var/lock/taskhub/)
- mode 0o600 lock file + 0o700 parent dir
- O_NOFOLLOW で symlink attack 排除
- LOCK_EX | LOCK_NB で non-blocking 排他、busy 時は blocker payload を返す
- exit 時 LOCK_UN + close (with context manager exit で確実 release)

Security invariants:
- raw secret を payload に含めない (subcommand / approval_id / pid / started_at のみ)
- lock file の世界読出禁止 (mode 0o600)
- symlink 経由の lock 取得試行は拒否 (O_NOFOLLOW)
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

LockReasonCode = Literal[
    "destructive_lock_acquired",
    "destructive_lock_busy",
    "destructive_lock_dir_missing",
    "destructive_lock_dir_permission",
    "destructive_lock_file_permission",
    "destructive_lock_payload_error",
]


def _lock_dir() -> Path:
    """ADV R1 F-002 adopt: env override で multi-user host 対応."""
    lock_dir_str = os.environ.get("TASKHUB_LOCK_DIR")
    if lock_dir_str:
        return Path(lock_dir_str)
    return Path.home() / ".taskhub" / "locks"


@contextmanager
def acquire_destructive_lock(
    subcommand: str,
    approval_id: str | None,
) -> Iterator[tuple[bool, LockReasonCode, dict[str, object] | None]]:
    """destructive operation lock を context manager で取得.

    yields:
        (acquired: bool, reason_code: LockReasonCode, blocker_payload: dict | None)

    - acquired=True なら with block 内で operation 実行可、exit 時に lock release.
    - acquired=False なら blocker_payload に保持者の
      {subcommand, approval_id, pid, started_at_utc} (取得可能な場合).
    """
    lock_dir = _lock_dir()
    try:
        lock_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    except OSError:
        yield False, "destructive_lock_dir_missing", None
        return

    # parent dir mode verify (0o700 必須)
    try:
        dir_mode = lock_dir.stat().st_mode & 0o777
    except OSError:
        yield False, "destructive_lock_dir_missing", None
        return
    if dir_mode != 0o700:
        yield False, "destructive_lock_dir_permission", None
        return

    lock_path = lock_dir / "destructive-operation.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    try:
        fd = os.open(str(lock_path), flags, 0o600)
    except OSError:
        yield False, "destructive_lock_file_permission", None
        return

    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # busy — payload を read してから caller に返す
            blocker: dict[str, object] | None
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                data = os.read(fd, 4096).decode("utf-8")
                blocker = json.loads(data) if data.strip() else None
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                blocker = None
            yield False, "destructive_lock_busy", blocker
            return

        # lock acquired — payload write
        payload = json.dumps(
            {
                "subcommand": subcommand,
                "approval_id": approval_id,
                "pid": os.getpid(),
                "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            sort_keys=True,
        )
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
        except OSError:
            # payload write 失敗でも lock は獲得済、release してから報告
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            yield False, "destructive_lock_payload_error", None
            return

        try:
            yield True, "destructive_lock_acquired", None
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


__all__ = [
    "LockReasonCode",
    "acquire_destructive_lock",
]
