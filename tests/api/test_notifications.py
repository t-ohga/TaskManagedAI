from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.api.approval_inbox import get_db_session
from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.main import create_app
from backend.app.seeds.initial import DEFAULT_ACTOR_ID

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

OTHER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000004002")
NOTIFICATION_ID = UUID("00000000-0000-4000-8000-000000004011")
OTHER_NOTIFICATION_ID = UUID("00000000-0000-4000-8000-000000004012")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-notifications-api",
        ),
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous_database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()

    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        command.upgrade(config, "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("TASKMANAGEDAI_DATABASE_URL", None)
        else:
            os.environ["TASKMANAGEDAI_DATABASE_URL"] = previous_database_url
        get_settings.cache_clear()


async def _assert_database_available(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("Notification API tests require a reachable test database.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
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
async def notification_api_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    app = create_app(_integration_settings())

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text("truncate notification_events, policy_decisions, approval_requests restart identity")
    )


async def _insert_tenant(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            on conflict (id) do update set
              name = excluded.name,
              metadata = excluded.metadata
            """
        )
    )


async def _insert_actor(
    session: AsyncSession,
    *,
    actor_id: UUID,
    stable_actor_id: str,
    display_name: str,
) -> None:
    await session.execute(
        text(
            """
            insert into actors (
              id,
              tenant_id,
              actor_type,
              actor_id,
              display_name,
              auth_context_hash,
              impersonated_by,
              metadata
            )
            values (
              :actor_uuid,
              1,
              'human',
              :stable_actor_id,
              :display_name,
              'notifications-api-auth-context',
              null,
              '{"rls_ready": true}'::jsonb
            )
            on conflict (id) do update set
              actor_type = excluded.actor_type,
              actor_id = excluded.actor_id,
              display_name = excluded.display_name,
              auth_context_hash = excluded.auth_context_hash,
              impersonated_by = excluded.impersonated_by,
              metadata = excluded.metadata
            """
        ),
        {
            "actor_uuid": actor_id,
            "stable_actor_id": stable_actor_id,
            "display_name": display_name,
        },
    )


async def _insert_notification(
    session: AsyncSession,
    *,
    notification_id: UUID,
    recipient_actor_id: UUID,
    read_at: datetime | None = None,
) -> None:
    await session.execute(
        text(
            """
            insert into notification_events (
              id,
              tenant_id,
              event_type,
              payload,
              recipient_actor_id,
              read_at
            )
            values (
              :id,
              1,
              'approval_pending',
              '{"approval_id": "00000000-0000-4000-8000-000000004099"}'::jsonb,
              :recipient_actor_id,
              :read_at
            )
            """
        ),
        {
            "id": notification_id,
            "recipient_actor_id": recipient_actor_id,
            "read_at": read_at,
        },
    )


async def _setup_notification_fixtures(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_tables(session)
        await _insert_tenant(session)
        await _insert_actor(
            session,
            actor_id=DEFAULT_ACTOR_ID,
            stable_actor_id="human:default",
            display_name="Default Human",
        )
        await _insert_actor(
            session,
            actor_id=OTHER_ACTOR_ID,
            stable_actor_id="human:notification-other",
            display_name="Other Human",
        )


@pytest.mark.asyncio
async def test_list_notifications_returns_recipient_only(
    notification_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_notification_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_notification(
            session,
            notification_id=NOTIFICATION_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
        )
        await _insert_notification(
            session,
            notification_id=OTHER_NOTIFICATION_ID,
            recipient_actor_id=OTHER_ACTOR_ID,
        )

    response = await notification_api_client.get("/api/v1/notifications")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [str(NOTIFICATION_ID)]


@pytest.mark.asyncio
async def test_badge_count_returns_unread_count(
    notification_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_notification_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_notification(
            session,
            notification_id=NOTIFICATION_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
        )
        await _insert_notification(
            session,
            notification_id=uuid4(),
            recipient_actor_id=DEFAULT_ACTOR_ID,
            read_at=datetime.now(tz=UTC),
        )
        await _insert_notification(
            session,
            notification_id=OTHER_NOTIFICATION_ID,
            recipient_actor_id=OTHER_ACTOR_ID,
        )

    response = await notification_api_client.get("/api/v1/notifications/badge_count")

    assert response.status_code == 200
    assert response.json() == {"unread_count": 1}


@pytest.mark.asyncio
async def test_mark_read_updates_read_at(
    notification_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_notification_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_notification(
            session,
            notification_id=NOTIFICATION_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
        )

    response = await notification_api_client.post(
        f"/api/v1/notifications/{NOTIFICATION_ID}/mark_read"
    )

    assert response.status_code == 200
    assert response.json()["read_at"] is not None

    badge_response = await notification_api_client.get("/api/v1/notifications/badge_count")
    assert badge_response.json() == {"unread_count": 0}


@pytest.mark.asyncio
async def test_mark_read_other_actor_returns_403(
    notification_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_notification_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_notification(
            session,
            notification_id=OTHER_NOTIFICATION_ID,
            recipient_actor_id=OTHER_ACTOR_ID,
        )

    response = await notification_api_client.post(
        f"/api/v1/notifications/{OTHER_NOTIFICATION_ID}/mark_read"
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "not your notification"


@pytest.mark.asyncio
async def test_mark_read_unknown_id_returns_404(
    notification_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_notification_fixtures(session_factory)

    response = await notification_api_client.post(f"/api/v1/notifications/{uuid4()}/mark_read")

    assert response.status_code == 404
    assert response.json()["detail"] == "notification not found"


@pytest.mark.asyncio
async def test_mark_read_idempotent_for_already_read(
    notification_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_notification_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_notification(
            session,
            notification_id=NOTIFICATION_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
            read_at=datetime.now(tz=UTC),
        )

    response = await notification_api_client.post(
        f"/api/v1/notifications/{NOTIFICATION_ID}/mark_read"
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(NOTIFICATION_ID)
    assert response.json()["read_at"] is not None

