"""SP-PHASE1 B4 (adversarial M2): host boot_id 安定化 unit test (ADR-00048 §A-2)。

macOS ``kern.boottime`` の raw string は末尾 human-readable timestamp が揺れ得るため、boot 時刻の
``sec``/``usec`` のみを抽出して boot_id とする。raw string をそのまま使うと同一 boot でも spawn 時と
kill 時で値が一致せず ``_killable`` が False → kill-miss (fail-open) になる。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.services.superintendent import host_identity


def _fake_run(stdout: str) -> object:
    def _run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(stdout=stdout, returncode=0)

    return _run


def test_macos_boot_id_extracts_stable_sec_usec_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """末尾 human-readable timestamp が異なっても同 boot なら同一 boot_id を返す (kill-miss 防止)。"""
    # 同一 boot (sec/usec 同じ) だが末尾 timestamp 表記が異なる 2 つの出力。
    out1 = "{ sec = 1718900000, usec = 123456 } Sat Jun 21 12:00:00 2026"
    out2 = "{ sec = 1718900000, usec = 123456 } Sat Jun 21 12:34:56 2026\n"

    monkeypatch.setattr(host_identity.subprocess, "run", _fake_run(out1))
    id1 = host_identity._macos_boot_id()
    monkeypatch.setattr(host_identity.subprocess, "run", _fake_run(out2))
    id2 = host_identity._macos_boot_id()

    assert id1 is not None
    assert id1 == id2  # 同 boot → 同一 boot_id (末尾 timestamp 揺れに非依存)。
    assert id1 == "macos-boottime:1718900000.123456"


def test_macos_boot_id_differs_across_reboots(monkeypatch: pytest.MonkeyPatch) -> None:
    out_boot_a = "{ sec = 1718900000, usec = 1 } Sat Jun 21 12:00:00 2026"
    out_boot_b = "{ sec = 1719000000, usec = 1 } Sun Jun 22 12:00:00 2026"
    monkeypatch.setattr(host_identity.subprocess, "run", _fake_run(out_boot_a))
    a = host_identity._macos_boot_id()
    monkeypatch.setattr(host_identity.subprocess, "run", _fake_run(out_boot_b))
    b = host_identity._macos_boot_id()
    assert a != b  # reboot で boot 時刻が変わる → boot_id も変わる。


def test_macos_boot_id_unparseable_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """想定外フォーマットは None (raw string を返さない = kill-miss リスクを作らない)。"""
    monkeypatch.setattr(host_identity.subprocess, "run", _fake_run("garbage output"))
    assert host_identity._macos_boot_id() is None


def test_macos_boot_id_empty_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_identity.subprocess, "run", _fake_run(""))
    assert host_identity._macos_boot_id() is None
