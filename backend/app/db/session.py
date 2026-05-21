from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings

logger = logging.getLogger(__name__)


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
# Codex PR #85 R3 F-R3-001 fix (P2): create_app(settings=...) 経由で resolved
# settings を inject 可能にする (idempotent reconfigure pattern)。
# import 時に default settings (env 経由) で attach、create_app() 内で
# `configure_active_registry_db_gate(settings=resolved_settings)` を呼べば
# 再 attach (前の listener を detach + 新 settings で attach)。
_DB_MUTATION_GATE_LISTENER: Callable[[Session], None] | None = None


def configure_active_registry_db_gate(settings: Settings | None = None) -> None:
    """Idempotent (re)attach: 前回の L3 listener を detach 後、新 settings で attach。

    - production startup: import 時に `settings=None` で attach (cached singleton)
    - test / programmatic app: `create_app(settings)` から再呼出で resolved Settings を反映
    - settings.active_registry_gate_enabled=False なら no-op (listener=None state)
    """
    global _DB_MUTATION_GATE_LISTENER
    from backend.app.db.active_registry_mutation_gate import (
        configure_db_mutation_gate_from_settings,
        detach_db_mutation_gate,
    )

    sync_class = AsyncSession.sync_session_class
    if _DB_MUTATION_GATE_LISTENER is not None:
        try:
            detach_db_mutation_gate(sync_class, _DB_MUTATION_GATE_LISTENER)
        except Exception as exc:  # noqa: BLE001 - 既に detach 済みなら OK
            logger.debug(
                "active_registry_db_gate_detach_during_reconfigure",
                extra={"exc": str(exc)},
            )
        _DB_MUTATION_GATE_LISTENER = None
    _DB_MUTATION_GATE_LISTENER = configure_db_mutation_gate_from_settings(
        sync_class, settings=settings
    )


# import 時に default cached settings で初期 attach
configure_active_registry_db_gate()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionFactory() as session:
        yield session


async def close_engine() -> None:
    await async_engine.dispose()

