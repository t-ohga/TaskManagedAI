from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
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
from backend.app.repositories.notification_event import NotificationEventRepository
from backend.app.seeds.initial import DEFAULT_ACTOR_ID

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

OTHER_ACTOR_ID = UUID("00000000-0000-4000-8000-000000004002")
NOTIFICATION_ID = UUID("00000000-0000-4000-8000-000000004011")
OTHER_NOTIFICATION_ID = UUID("00000000-0000-4000-8000-000000004012")
HIGH_NOTIFICATION_ID = UUID("00000000-0000-4000-8000-000000004013")
SNOOZED_NOTIFICATION_ID = UUID("00000000-0000-4000-8000-000000004014")
RESOLVED_NOTIFICATION_ID = UUID("00000000-0000-4000-8000-000000004015")


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
        text(
            "truncate audit_events, notification_events, policy_decisions, "
            "approval_requests restart identity cascade"
        )
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
    severity: str = "info",
    required_action: str = "acknowledge",
    due_at: datetime | None = None,
    snoozed_until: datetime | None = None,
    resolved_at: datetime | None = None,
    resolved_by_actor_id: UUID | None = None,
    dedupe_key: str | None = None,
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
              read_at,
              severity,
              required_action,
              due_at,
              snoozed_until,
              resolved_at,
              resolved_by_actor_id,
              dedupe_key
            )
            values (
              :id,
              1,
              'approval_pending',
              '{"approval_id": "00000000-0000-4000-8000-000000004099"}'::jsonb,
              :recipient_actor_id,
              :read_at,
              :severity,
              :required_action,
              :due_at,
              :snoozed_until,
              :resolved_at,
              :resolved_by_actor_id,
              :dedupe_key
            )
            """
        ),
        {
            "id": notification_id,
            "recipient_actor_id": recipient_actor_id,
            "read_at": read_at,
            "severity": severity,
            "required_action": required_action,
            "due_at": due_at,
            "snoozed_until": snoozed_until,
            "resolved_at": resolved_at,
            "resolved_by_actor_id": resolved_by_actor_id,
            "dedupe_key": dedupe_key,
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
async def test_triage_lists_open_owned_items_without_raw_payload_values(
    notification_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_notification_fixtures(session_factory)
    now = datetime.now(tz=UTC)
    async with session_factory.begin() as session:
        await _insert_notification(
            session,
            notification_id=NOTIFICATION_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
            severity="critical",
            required_action="resolve_blocker",
            due_at=now + timedelta(days=2),
        )
        await _insert_notification(
            session,
            notification_id=HIGH_NOTIFICATION_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
            severity="high",
            required_action="review_approval",
            due_at=now + timedelta(days=1),
        )
        await _insert_notification(
            session,
            notification_id=OTHER_NOTIFICATION_ID,
            recipient_actor_id=OTHER_ACTOR_ID,
            severity="critical",
            required_action="resolve_blocker",
        )
        await _insert_notification(
            session,
            notification_id=SNOOZED_NOTIFICATION_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
            severity="critical",
            required_action="inspect_run",
            snoozed_until=now + timedelta(hours=2),
        )
        await _insert_notification(
            session,
            notification_id=RESOLVED_NOTIFICATION_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
            severity="critical",
            required_action="acknowledge",
            resolved_at=now,
            resolved_by_actor_id=DEFAULT_ACTOR_ID,
        )

    response = await notification_api_client.get("/api/v1/notifications/triage")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [str(NOTIFICATION_ID), str(HIGH_NOTIFICATION_ID)]
    assert payload[0]["payload_keys"] == ["approval_id"]
    assert payload[0]["payload_redaction_status"] == "keys_only"
    assert "payload" not in payload[0]
    assert payload[0]["severity"] == "critical"
    assert payload[0]["required_action"] == "resolve_blocker"

    snoozed_response = await notification_api_client.get("/api/v1/notifications/triage?state=snoozed")
    assert snoozed_response.status_code == 200
    assert [item["id"] for item in snoozed_response.json()] == [str(SNOOZED_NOTIFICATION_ID)]

    resolved_response = await notification_api_client.get(
        "/api/v1/notifications/triage?state=resolved"
    )
    assert resolved_response.status_code == 200
    assert [item["id"] for item in resolved_response.json()] == [str(RESOLVED_NOTIFICATION_ID)]


@pytest.mark.asyncio
async def test_triage_snooze_updates_unresolved_owned_notification_and_audits_metadata_only(
    notification_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_notification_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_notification(
            session,
            notification_id=NOTIFICATION_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
            severity="medium",
            required_action="inspect_run",
            dedupe_key="agent-run:demo",
        )

    snoozed_until = datetime.now(tz=UTC) + timedelta(hours=4)
    response = await notification_api_client.post(
        f"/api/v1/notifications/{NOTIFICATION_ID}/snooze",
        json={"snoozed_until": snoozed_until.isoformat()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(NOTIFICATION_ID)
    assert payload["snoozed_until"] is not None
    assert payload["payload_redaction_status"] == "keys_only"
    assert "payload" not in payload

    async with session_factory() as session:
        audit_payload = await session.scalar(
            text(
                """
                select event_payload
                from audit_events
                where tenant_id = 1
                  and event_type = 'notification_snoozed'
                order by created_at desc
                limit 1
                """
            )
        )

    assert isinstance(audit_payload, dict)
    assert audit_payload["notification_id"] == str(NOTIFICATION_ID)
    assert audit_payload["severity"] == "medium"
    assert "dedupe_key" not in audit_payload


@pytest.mark.asyncio
async def test_triage_resolve_marks_read_clears_snooze_and_omits_resolution_note_body(
    notification_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_notification_fixtures(session_factory)
    note = "private resolution note that must not be stored in the audit payload"
    async with session_factory.begin() as session:
        await _insert_notification(
            session,
            notification_id=NOTIFICATION_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
            severity="high",
            required_action="review_approval",
            snoozed_until=datetime.now(tz=UTC) + timedelta(hours=2),
        )

    response = await notification_api_client.post(
        f"/api/v1/notifications/{NOTIFICATION_ID}/resolve",
        json={"resolution_note": note},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resolved_at"] is not None
    assert payload["resolved_by_actor_id"] == str(DEFAULT_ACTOR_ID)
    assert payload["snoozed_until"] is None
    assert payload["read_at"] is not None

    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    """
                    select resolved_at, resolved_by_actor_id, snoozed_until, read_at
                    from notification_events
                    where tenant_id = 1 and id = :notification_id
                    """
                ),
                {"notification_id": NOTIFICATION_ID},
            )
        ).mappings().one()
        audit_payload = await session.scalar(
            text(
                """
                select event_payload
                from audit_events
                where tenant_id = 1
                  and event_type = 'notification_resolved'
                order by created_at desc
                limit 1
                """
            )
        )

    assert row["resolved_at"] is not None
    assert row["resolved_by_actor_id"] == DEFAULT_ACTOR_ID
    assert row["snoozed_until"] is None
    assert row["read_at"] is not None
    assert isinstance(audit_payload, dict)
    assert audit_payload["resolution_note_present"] is True
    assert note not in str(audit_payload)


@pytest.mark.asyncio
async def test_triage_snooze_other_actor_returns_403(
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
        f"/api/v1/notifications/{OTHER_NOTIFICATION_ID}/snooze",
        json={"snoozed_until": (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat()},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "not your notification"


@pytest.mark.asyncio
async def test_triage_resolve_already_resolved_returns_409_without_duplicate_audit(
    notification_api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _setup_notification_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_notification(
            session,
            notification_id=RESOLVED_NOTIFICATION_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
            resolved_at=datetime.now(tz=UTC),
            resolved_by_actor_id=DEFAULT_ACTOR_ID,
        )

    response = await notification_api_client.post(
        f"/api/v1/notifications/{RESOLVED_NOTIFICATION_ID}/resolve",
        json={},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "notification already resolved"

    async with session_factory() as session:
        audit_count = await session.scalar(
            text(
                """
                select count(*)
                from audit_events
                where tenant_id = 1 and event_type = 'notification_resolved'
                """
            )
        )

    assert audit_count == 0


@pytest.mark.asyncio
async def test_triage_snooze_rejects_past_deadlines(
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
        f"/api/v1/notifications/{NOTIFICATION_ID}/snooze",
        json={"snoozed_until": (datetime.now(tz=UTC) - timedelta(minutes=1)).isoformat()},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "snoozed_until must be in the future"


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
async def test_resolve_rejects_cross_recipient_notification(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Codex adversarial R1 (HIGH): repo.resolve は recipient_actor_id guard を WHERE に持つため、
    # 別 recipient 宛通知 (MCP 経路は REST の _assert_owned が無い) を別 actor が resolve して相手の
    # triage から消すことはできない (0 rows→None、row は未解決のまま)。
    await _setup_notification_fixtures(session_factory)
    async with session_factory.begin() as session:
        await _insert_notification(
            session,
            notification_id=OTHER_NOTIFICATION_ID,
            recipient_actor_id=OTHER_ACTOR_ID,
        )

    async with session_factory() as session:
        repo = NotificationEventRepository(session)
        result = await repo.resolve(
            tenant_id=1,
            event_id=OTHER_NOTIFICATION_ID,
            resolved_by_actor_id=DEFAULT_ACTOR_ID,
            recipient_actor_id=DEFAULT_ACTOR_ID,
        )
        await session.commit()

    assert result is None

    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    """
                    select resolved_at, resolved_by_actor_id, read_at
                    from notification_events
                    where tenant_id = 1 and id = :notification_id
                    """
                ),
                {"notification_id": OTHER_NOTIFICATION_ID},
            )
        ).mappings().one()

    assert row["resolved_at"] is None
    assert row["resolved_by_actor_id"] is None
    assert row["read_at"] is None


@pytest.mark.asyncio
async def test_bridge_notification_resolve_self_resolves_audits_and_blocks_cross_recipient(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Codex adversarial R2 (HIGH): MCP bridge は (1) 自分 (superintendent) 宛通知のみ resolve でき、
    # (2) notification_resolved audit を残し、(3) 別 recipient 宛通知は not_found で state 不変。
    # P0 では DEFAULT_ACTOR_ID == DEFAULT_SUPERINTENDENT_ACTOR_ID (同一 UUID)。
    from backend.app.mcp.api_bridge import bridge_notification_resolve

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

    async with session_factory() as session:
        resolved = await bridge_notification_resolve(
            session, tenant_id=1, notification_id=NOTIFICATION_ID
        )
    assert resolved == {"notification_id": str(NOTIFICATION_ID), "resolved": True}

    async with session_factory() as session:
        denied = await bridge_notification_resolve(
            session, tenant_id=1, notification_id=OTHER_NOTIFICATION_ID
        )
    assert denied == {"error": "not_found", "notification_id": str(OTHER_NOTIFICATION_ID)}

    async with session_factory() as session:
        own_resolved_at = await session.scalar(
            text(
                "select resolved_at from notification_events where tenant_id = 1 and id = :id"
            ),
            {"id": NOTIFICATION_ID},
        )
        other_resolved_at = await session.scalar(
            text(
                "select resolved_at from notification_events where tenant_id = 1 and id = :id"
            ),
            {"id": OTHER_NOTIFICATION_ID},
        )
        audit_count = await session.scalar(
            text(
                """
                select count(*)
                from audit_events
                where tenant_id = 1 and event_type = 'notification_resolved'
                """
            )
        )
        audit_payload = await session.scalar(
            text(
                """
                select event_payload
                from audit_events
                where tenant_id = 1 and event_type = 'notification_resolved'
                order by created_at desc
                limit 1
                """
            )
        )

    assert own_resolved_at is not None
    assert other_resolved_at is None
    assert audit_count == 1
    # R3: MCP resolve audit は via=mcp marker を持ち、raw notification payload (approval_id 等) を
    # 混入しない (metadata-only)。
    assert isinstance(audit_payload, dict)
    assert audit_payload["via"] == "mcp"
    assert audit_payload["notification_id"] == str(NOTIFICATION_ID)
    assert "approval_id" not in audit_payload


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
