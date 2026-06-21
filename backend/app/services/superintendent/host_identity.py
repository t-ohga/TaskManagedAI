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
import re
import subprocess  # noqa: S404 — sysctl read-only 呼出のみ (shell=False、固定 argv)

#: macOS ``kern.boottime`` の安定部分 (boot 時刻 sec/usec) のみを抽出する正規表現。
#: 例: ``{ sec = 1718900000, usec = 123456 } Sat Jun 21 12:00:00 2026``
#: 末尾の human-readable timestamp は OS / locale 依存で揺れ得るため使わない (M2: kill-miss 防止)。
_MACOS_BOOTTIME_RE = re.compile(r"sec\s*=\s*(\d+)\D+usec\s*=\s*(\d+)")


def _linux_boot_id() -> str | None:
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as fh:
            value = fh.read().strip()
        return value or None
    except OSError:
        return None


def _macos_boot_id() -> str | None:
    """``kern.boottime`` を安定 id 化する (reboot で変化する boot 時刻)。

    **M2 (adversarial review adopt)**: ``sysctl -n kern.boottime`` の出力は末尾に human-readable
    timestamp を含み OS / locale 依存で揺れ得る。raw string をそのまま boot_id にすると、spawn 時
    (mark_running) と kill 時で同一 boot でも値が一致せず ``_killable`` が False → **kill-miss
    (fail-open)** になる。よって安定部分 (boot 時刻の ``sec`` / ``usec``) のみを抽出して boot_id とする。
    """
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
    raw = result.stdout.strip()
    if not raw:
        return None
    match = _MACOS_BOOTTIME_RE.search(raw)
    if match is None:
        # 想定外フォーマット時は boot_id 取得不能扱い (boot 時刻の安定抽出ができないなら照合を無効化、
        # host scope が主防御。raw string を返すと kill-miss リスクのため返さない)。
        return None
    return f"macos-boottime:{match.group(1)}.{match.group(2)}"


def get_host_boot_id() -> str | None:
    """現 host の boot_id を返す (取得不能なら None)。"""
    system = platform.system()
    if system == "Linux":
        return _linux_boot_id()
    if system == "Darwin":
        return _macos_boot_id()
    return None


__all__ = ["get_host_boot_id"]
