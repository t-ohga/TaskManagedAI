"""SP022-T02 Phase 2 / T08 batch 2 — real tool integration stubs.

F-014 adopt: actual `taskhub backup` execution validation は SP022-T09 mandatory drill
checklist で覆われる。本 file は real tool (pg_dump / redis-cli / age) installed 時のみ
run、autonomous test env では skip。

SP022-T09 mandatory drill checklist marker (docs/deploy/half-yearly-drill-sop.md §11):
- actual `taskhub backup` 実行 with signed approval
- age decrypt dry-run + tar listing
- checksums verify (sha256sum -c)
- pg_restore 互換確認 (separate restore drill, T02 Phase 3 carry-over)
- private key 非混入確認 (tar listing から grep)
- cleanup verify (tmp dir 不在)
"""

from __future__ import annotations

import shutil

import pytest

REAL_TOOLS_AVAILABLE = bool(
    shutil.which("pg_dump") and shutil.which("redis-cli") and shutil.which("age"),
)


@pytest.mark.skipif(
    not REAL_TOOLS_AVAILABLE,
    reason=(
        "real tools (pg_dump / redis-cli / age) not installed in autonomous test env; "
        "covered by SP022-T09 mandatory drill checklist (docs/deploy/half-yearly-drill-sop.md §11)"
    ),
)
def test_taskhub_backup_real_io_smoke_placeholder() -> None:
    """Placeholder for real-tool smoke test.

    Actual implementation requires Docker + pg + Redis + age installed + signed approval
    record + age key pair。SP022-T09 で実機 drill 時に展開予定。
    """
    pytest.skip("SP022-T09 carry-over: full real-tool smoke test")
