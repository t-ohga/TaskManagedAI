"""MaterialReconciliationService.gc_orphans の入力検証 (no-DB、Codex R5-F1)。

grace の正整数強制は service 入口で行う (CLI validator だけでは run_gc_orphans() や本 method を直接
呼ぶ経路を保護できない)。検証は _ensure_tenant_context (session 利用) より前に発火するため session は
MagicMock で良い。実 reconciliation の DB e2e は S4 (batch-3) の DB-gated suite が担当。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.app.services.secrets.material_reconciliation import (
    MaterialReconciliationService,
)


def _service() -> MaterialReconciliationService:
    return MaterialReconciliationService(session=MagicMock(), store=MagicMock())


@pytest.mark.parametrize("bad", [0, -1, -300])
async def test_gc_orphans_rejects_non_positive_grace(bad: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        await _service().gc_orphans(tenant_id=1, writing_grace_seconds=bad)


@pytest.mark.parametrize("bad", [True, False])
async def test_gc_orphans_rejects_bool_grace(bad: bool) -> None:
    # bool は int subclass だが grace としては不正 (True→1 秒等の footgun を防ぐ)。
    with pytest.raises(ValueError, match="int"):
        await _service().gc_orphans(tenant_id=1, writing_grace_seconds=bad)


@pytest.mark.parametrize("bad", ["300", 1.5, None])
async def test_gc_orphans_rejects_non_int_grace(bad: object) -> None:
    with pytest.raises(ValueError, match="int"):
        await _service().gc_orphans(tenant_id=1, writing_grace_seconds=bad)  # type: ignore[arg-type]
