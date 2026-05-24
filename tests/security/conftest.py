from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.api.approval_inbox import get_db_session
from backend.app.db.session import create_engine
from backend.app.main import create_app
from tests.cli.test_capability_token_lifecycle import (
    _assert_database_available,
    _integration_settings,
    _run_alembic_upgrade,
)


@pytest_asyncio.fixture
async def cli_capability_session_factory() -> AsyncIterator[
    async_sessionmaker[AsyncSession]
]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)

    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def cli_capability_client(
    cli_capability_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    app = create_app(_integration_settings())

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with cli_capability_session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
