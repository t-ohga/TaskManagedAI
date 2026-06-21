"""taskhub secret-gc-orphans CLI helper (ADR-00059 / batch-1 revoke backstop)。

revoke 失敗時に残る local material orphan (status='revoked' AND material_purged_at IS NULL) と
create/rotate の writing-orphan を ``MaterialReconciliationService`` で idempotent に reconcile する
**operational path**。これにより revoke の durable convergence (失敗しても再実行で material 削除に収束)
が実際に invokable になる (Codex R3-F1: service だけでは runtime caller が無く durable convergence を
主張できない)。

raw secret 値は一切出力しない (secret_ref_id と件数のみ)。
"""

from __future__ import annotations

import asyncio
from typing import Any

DEFAULT_WRITING_GRACE_SECONDS = 300


def run_gc_orphans(
    *,
    tenant_id: int,
    database_url: str | None = None,
    writing_grace_seconds: int = DEFAULT_WRITING_GRACE_SECONDS,
) -> dict[str, Any]:
    """tenant scoped に gc-orphans を実行し report dict を返す (asyncio.run bridge)。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.services.secrets.local_secret_store import LocalSecretStore
    from backend.app.services.secrets.material_reconciliation import (
        MaterialReconciliationService,
    )

    if database_url is None:
        from backend.app.config import get_settings

        database_url = get_settings().database_url

    async def _run() -> dict[str, Any]:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            factory = async_sessionmaker(bind=engine, expire_on_commit=False)
            async with factory() as session:
                service = MaterialReconciliationService(session, LocalSecretStore())
                report = await service.gc_orphans(
                    tenant_id=tenant_id,
                    writing_grace_seconds=writing_grace_seconds,
                )
                return {
                    "tenant_id": tenant_id,
                    "purged": report.purged,
                    "purge_failed": report.purge_failed,
                    "rolled_back": report.rolled_back,
                    "total_actions": report.total_actions,
                }
        finally:
            await engine.dispose()

    return asyncio.run(_run())


__all__ = ["DEFAULT_WRITING_GRACE_SECONDS", "run_gc_orphans"]
