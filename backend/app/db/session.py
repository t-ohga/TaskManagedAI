from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.config import get_settings


def create_engine(database_url: str | None = None) -> AsyncEngine:
    return create_async_engine(
        database_url or get_settings().database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


async_engine = create_engine()
AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
)


# SP-012 §9.10 R10 F-001: L3 active-registry DB mutation gate wiring。
# Codex PR #85 R1 F-004 fix (P1): production wiring を実装。
# Settings.active_registry_gate_enabled=True なら AsyncSession の sync_session_class
# に `before_commit` listener を attach (SQLAlchemy async event は sync session class
# 経由で dispatch される、公式 docs 準拠)。disabled (default) なら no-op。
# import 時に attach するため、production startup で host_id 未設定なら ValueError raise
# (process startup abort)。
def _wire_db_mutation_gate() -> None:
    """import 時の 1 回限り attach (idempotent ではないため重複呼出禁止)。

    SQLAlchemy async events は `AsyncSession.sync_session_class` (デフォルト
    `sqlalchemy.orm.Session`) の event を経由して dispatch される (公式 docs)。
    """
    from backend.app.db.active_registry_mutation_gate import (
        configure_db_mutation_gate_from_settings,
    )

    sync_class = AsyncSession.sync_session_class
    configure_db_mutation_gate_from_settings(sync_class)


_wire_db_mutation_gate()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionFactory() as session:
        yield session


async def close_engine() -> None:
    await async_engine.dispose()

