"""MCP Server context: DB session factory + tenant/actor resolution."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import get_settings
from backend.app.db.session import create_engine

_session_factory: async_sessionmaker[AsyncSession] | None = None

DEFAULT_TENANT_ID = 1
DEFAULT_SUPERINTENDENT_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000001")


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        settings = get_settings()
        engine = create_engine(settings.database_url)
        _session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
