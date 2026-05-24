from __future__ import annotations

import asyncio
import hashlib
import os
from collections import Counter
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

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
from backend.app.services.auth import ApiCapabilityTokenDenied, ApiCapabilityTokenService

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000016201")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000016202")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000016203")
AUTH_CONTEXT_HASH = "a" * 64
REQUEST_BINDING_HASH = "b" * 64


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-cli-token-lifecycle",
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous_database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(_REPO_ROOT / "alembic.ini")), "head")
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
            raise AssertionError("CLI capability token tests require PostgreSQL.") from exc
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
async def cli_auth_client(
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
            """
            truncate
              api_capability_tokens,
              audit_events,
              principals,
              projects,
              workspaces,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _insert_fixture(session: AsyncSession) -> None:
    await _reset_tables(session)
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            """
        )
    )
    await session.execute(
        text(
            """
            insert into actors (
              id, tenant_id, actor_type, actor_id, display_name, metadata
            )
            values (
              :actor_id, 1, 'human', 'human:default', 'Default Human',
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (
              :workspace_id, 1, 'cli-token-workspace', 'cli-token-workspace',
              :actor_id, '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (
              :project_id, 1, :workspace_id, 'cli-token-project',
              'cli-token-project', 'active', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
    )


def _issue_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "project_id": str(PROJECT_ID),
        "device_id": "macbook-pro-dev",
        "allowed_actions": ["task_list", "task_show", "task_write"],
        "scope_constraint": {"project_id": str(PROJECT_ID), "profile": "default"},
        "auth_method": "keyring",
        "auth_context_hash": AUTH_CONTEXT_HASH,
        "request_binding_hash": REQUEST_BINDING_HASH,
        "ttl_minutes": 5,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_service_issues_hash_only_token_and_ref_only_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_fixture(session)
        result = await ApiCapabilityTokenService(session).issue(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            project_id=PROJECT_ID,
            device_id="macbook-pro-dev",
            allowed_actions=["task_list", "task_show"],
            scope_constraint={"project_id": str(PROJECT_ID)},
            auth_method="keyring",
            auth_context_hash=AUTH_CONTEXT_HASH,
            request_binding_hash=REQUEST_BINDING_HASH,
            ttl_minutes=5,
        )
        await session.commit()

        rows = (
            await session.execute(
                text(
                    """
                    select token_hash, status, allowed_actions, principal_id
                      from api_capability_tokens
                     where tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
        ).mappings().all()
        principal_type = await session.scalar(
            text("select principal_type from principals where id = :principal_id"),
            {"principal_id": result.token.principal_id},
        )
        audit_payloads = (
            await session.execute(
                text(
                    """
                    select event_type, event_payload
                      from audit_events
                     where tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
        ).mappings().all()

    assert len(rows) == 1
    assert rows[0]["status"] == "issued"
    assert rows[0]["token_hash"] == hashlib.sha256(
        result.raw_operation_token.encode("utf-8")
    ).hexdigest()
    assert result.raw_operation_token not in repr(rows)
    assert principal_type == "capability_token"
    assert [row["event_type"] for row in audit_payloads] == [
        "api_capability_token_issued"
    ]
    assert result.raw_operation_token not in repr(audit_payloads)
    assert dict(audit_payloads[0]["event_payload"])["redaction_status"] == "ref_only"


@pytest.mark.asyncio
async def test_service_rejects_plain_auth_method_and_audits_denial(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_fixture(session)

        with pytest.raises(ApiCapabilityTokenDenied) as denied:
            await ApiCapabilityTokenService(session).issue(
                tenant_id=TENANT_ID,
                actor_id=ACTOR_ID,
                project_id=PROJECT_ID,
                device_id="macbook-pro-dev",
                allowed_actions=["task_write"],
                scope_constraint={"project_id": str(PROJECT_ID)},
                auth_method="plain",
                auth_context_hash=AUTH_CONTEXT_HASH,
                request_binding_hash=REQUEST_BINDING_HASH,
                ttl_minutes=5,
            )
        await session.commit()

        token_count = await session.scalar(text("select count(*) from api_capability_tokens"))
        audit = (
            await session.execute(
                text("select event_type, event_payload from audit_events")
            )
        ).mappings().one()

    assert denied.value.reason_code == "plain_auth_method_rejected"
    assert token_count == 0
    assert audit["event_type"] == "api_capability_token_denied"
    assert dict(audit["event_payload"])["reason_code"] == "plain_auth_method_rejected"


@pytest.mark.asyncio
async def test_service_refresh_rejects_invalid_ttl_before_revoking_current_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_fixture(session)
        issued = await ApiCapabilityTokenService(session).issue(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            project_id=PROJECT_ID,
            device_id="macbook-pro-dev",
            allowed_actions=["task_list"],
            scope_constraint={"project_id": str(PROJECT_ID)},
            auth_method="keyring",
            auth_context_hash=AUTH_CONTEXT_HASH,
            request_binding_hash=REQUEST_BINDING_HASH,
            ttl_minutes=5,
        )

        with pytest.raises(ApiCapabilityTokenDenied) as denied:
            await ApiCapabilityTokenService(session).refresh(
                tenant_id=TENANT_ID,
                actor_id=ACTOR_ID,
                raw_operation_token=issued.raw_operation_token,
                ttl_minutes=31,
            )
        await session.commit()

        status_value = await session.scalar(
            text("select status from api_capability_tokens where id = :token_id"),
            {"token_id": issued.token.id},
        )
        event_types = (
            await session.execute(
                text("select event_type from audit_events order by created_at, id")
            )
        ).scalars().all()

    assert denied.value.reason_code == "ttl_out_of_bounds"
    assert status_value == "issued"
    assert Counter(event_types) == {
        "api_capability_token_issued": 1,
        "api_capability_token_denied": 1,
    }


@pytest.mark.asyncio
async def test_cli_auth_endpoints_issue_refresh_and_revoke(
    session_factory: async_sessionmaker[AsyncSession],
    cli_auth_client: AsyncClient,
) -> None:
    async with session_factory() as session:
        await _insert_fixture(session)
        await session.commit()

    issued = await cli_auth_client.post("/api/v1/auth/cli-login", json=_issue_payload())
    assert issued.status_code == 200
    issued_body = issued.json()
    assert issued_body["status"] == "issued"
    assert issued_body["operation_token"]

    refreshed = await cli_auth_client.post(
        "/api/v1/auth/cli-token/refresh",
        json={"operation_token": issued_body["operation_token"], "ttl_minutes": 5},
    )
    assert refreshed.status_code == 200
    refreshed_body = refreshed.json()
    assert refreshed_body["operation_token"] != issued_body["operation_token"]

    revoked = await cli_auth_client.post(
        "/api/v1/auth/cli-token/revoke",
        json={"operation_token": refreshed_body["operation_token"]},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    async with session_factory() as session:
        statuses = (
            await session.execute(
                text(
                    """
                    select status
                      from api_capability_tokens
                     order by issued_at, id
                    """
                )
            )
        ).scalars().all()
        event_types = (
            await session.execute(
                text("select event_type from audit_events order by created_at, id")
            )
        ).scalars().all()

    assert statuses == ["revoked", "revoked"]
    assert Counter(event_types) == {
        "api_capability_token_issued": 2,
        "api_capability_token_revoked": 2,
    }


@pytest.mark.asyncio
async def test_cli_login_endpoint_rejects_plain_auth_method(
    session_factory: async_sessionmaker[AsyncSession],
    cli_auth_client: AsyncClient,
) -> None:
    async with session_factory() as session:
        await _insert_fixture(session)
        await session.commit()

    response = await cli_auth_client.post(
        "/api/v1/auth/cli-login",
        json=_issue_payload(auth_method="plain"),
    )
    assert response.status_code == 400
    assert response.json()["detail"]["reason_code"] == "plain_auth_method_rejected"

    async with session_factory() as session:
        token_count = await session.scalar(text("select count(*) from api_capability_tokens"))
        event_payload = await session.scalar(
            text("select event_payload from audit_events limit 1")
        )

    assert token_count == 0
    assert dict(event_payload)["reason_code"] == "plain_auth_method_rejected"
