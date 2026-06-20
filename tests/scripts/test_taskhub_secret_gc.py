"""taskhub secret-gc-orphans CLI の wiring test (no-DB、ADR-00059 R3-F1)。

実 gc-orphans の DB e2e (purge / tombstone / 再試行収束) は S4 (batch-3) の DB-gated suite が担当。
本 test は subparser 配線 + helper importability + tenant scope 必須を固める。
"""

from __future__ import annotations

import pytest

from scripts.taskhub_admin import _build_parser, _cmd_secret_gc_orphans
from scripts.taskhub_secret_gc import DEFAULT_WRITING_GRACE_SECONDS, run_gc_orphans


def test_secret_gc_orphans_subparser_wired() -> None:
    parser = _build_parser()
    args = parser.parse_args(["secret-gc-orphans", "--tenant-id", "1"])
    assert args.func is _cmd_secret_gc_orphans
    assert args.tenant_id == 1
    assert args.writing_grace_seconds == DEFAULT_WRITING_GRACE_SECONDS
    assert args.database_url is None


def test_secret_gc_orphans_requires_tenant_id() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):  # --tenant-id 必須 (tenant scoped)
        parser.parse_args(["secret-gc-orphans"])


def test_secret_gc_orphans_accepts_overrides() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "secret-gc-orphans",
            "--tenant-id",
            "2",
            "--writing-grace-seconds",
            "60",
            "--database-url",
            "postgresql+asyncpg://x/y",
        ]
    )
    assert args.tenant_id == 2
    assert args.writing_grace_seconds == 60
    assert args.database_url == "postgresql+asyncpg://x/y"


def test_run_gc_orphans_is_importable() -> None:
    # helper が import 可能で callable (実行は DB 必要、S4 で e2e)。
    assert callable(run_gc_orphans)
