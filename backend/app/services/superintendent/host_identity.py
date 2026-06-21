"""Host boot identity helper (SP-PHASE1 B2、ADR-00048 §Amendment A-2)。

pid/pgid 再利用防御のため、kill 前に host の ``boot_id`` を managed_agents row と照合する。
boot_id は OS reboot ごとに変わる安定 id で、死亡 process の pgid を無関係 process が再利用していた
場合の誤 kill を防ぐ (boot_id 不一致なら signal しない)。

- Linux: ``/proc/sys/kernel/random/boot_id`` (UUID 形式、reboot で変化)。
- macOS: ``sysctl kern.boottime`` 由来の boot 時刻を安定 id 化 (Linux boot_id 相当)。
- 取得不能時は ``None`` を返す (fallback、kill 側は boot_id 照合を best-effort とする)。

本 helper は副作用なし (read-only)。secret を扱わない。
"""

from __future__ import annotations

import platform
import subprocess  # noqa: S404 — sysctl read-only 呼出のみ (shell=False、固定 argv)


def _linux_boot_id() -> str | None:
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as fh:
            value = fh.read().strip()
        return value or None
    except OSError:
        return None


def _macos_boot_id() -> str | None:
    """``kern.boottime`` を安定 id 化する (reboot で変化する boot 時刻 string)。"""
    try:
        result = subprocess.run(  # noqa: S603 — 固定 argv, shell=False, no user input
            ["/usr/sbin/sysctl", "-n", "kern.boottime"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def get_host_boot_id() -> str | None:
    """現 host の boot_id を返す (取得不能なら None)。"""
    system = platform.system()
    if system == "Linux":
        return _linux_boot_id()
    if system == "Darwin":
        return _macos_boot_id()
    return None


__all__ = ["get_host_boot_id"]
