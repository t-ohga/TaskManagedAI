from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ONE_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000701")
TENANT_TWO_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000702")
SECRET_REF_ONE_ID = UUID("00000000-0000-4000-8000-000000000711")
SECRET_REF_TWO_ID = UUID("00000000-0000-4000-8000-000000000712")
SECRET_REF_THREE_ID = UUID("00000000-0000-4000-8000-000000000713")
TOKEN_ONE_ID = UUID("00000000-0000-4000-8000-000000000721")
TOKEN_TWO_ID = UUID("00000000-0000-4000-8000-000000000722")

PROHIBITED_SECRET_COLUMNS = frozenset(
    {
        "age_key",
        "api_key",
        "auth_token",
        "canary",
        "plaintext",
        "private_key",
        "raw_secret",
        "raw_token",
        "raw_value",
        "request_fingerprint",
        "secret_value",
        "sops_key",
        "token",
        "value",
    }
)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-secret-constraint-tests",
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
            raise AssertionError("Secret constraint tests require a reachable test database.") from exc
        pytest.skip("Set TASKMANAGEDAI_RUN_DB_TESTS=1 with test PostgreSQL running.")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = _integration_settings()
    await _assert_database_available(settings)
    await asyncio.to_thread(_run_alembic_upgrade, settings.database_url)

    engine = create_engine(settings.database_url)
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        yield factory
    finally:
        await engine.dispose()


def _sqlstate(error: BaseException) -> str | None:
    queue: list[BaseException] = [error]
    seen: set[int] = set()

    while queue:
        current = queue.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))

        state = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if isinstance(state, str):
            return state

        cause = current.__cause__
        if cause is not None:
            queue.append(cause)

        context = current.__context__
        if context is not None:
            queue.append(context)

        for arg in getattr(current, "args", ()):
            if isinstance(arg, BaseException):
                queue.append(arg)

    return None


def _assert_integrity_error(
    error: IntegrityError,
    *,
    sqlstate: str,
    constraint_name: str | tuple[str, ...],
) -> None:
    assert _sqlstate(error) == sqlstate
    error_message = str(error)
    if isinstance(constraint_name, str):
        assert constraint_name in error_message
        return

    assert any(name in error_message for name in constraint_name), error_message


async def _reset_secret_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              secret_capability_tokens,
              secret_refs,
              notification_events,
              audit_events,
              ticket_relations,
              acceptance_criteria,
              tickets,
              repositories,
              projects,
              workspaces,
              principals,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _insert_tenant(session: AsyncSession, tenant_id: int, name: str) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (:tenant_id, :name, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"tenant_id": tenant_id, "name": name},
    )


async def _insert_actor(
    session: AsyncSession,
    *,
    tenant_id: int,
    actor_id: UUID,
    stable_actor_id: str,
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
              metadata
            )
            values (
              :actor_uuid,
              :tenant_id,
              'human',
              :stable_actor_id,
              'Secret Constraint Actor',
              'secret-constraint-auth-context',
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "actor_uuid": actor_id,
            "tenant_id": tenant_id,
            "stable_actor_id": stable_actor_id,
        },
    )


async def _insert_secret_ref(
    session: AsyncSession,
    *,
    id: UUID,
    tenant_id: int = 1,
    owner_actor_id: UUID = TENANT_ONE_ACTOR_ID,
    scope: str = "project",
    name: str = "provider-openai",
    version: str = "v1",
    status: str = "active",
    secret_uri: str | None = None,
    runner_injectable: bool = False,
    allowed_consumers: str = '["api:provider_adapter"]',
    allowed_operations: str = '["provider.call"]',
    metadata: str = '{"rls_ready": true}',
) -> None:
    await session.execute(
        text(
            """
            insert into secret_refs (
              id,
              tenant_id,
              secret_uri,
              scope,
              name,
              version,
              status,
              runner_injectable,
              allowed_consumers,
              allowed_operations,
              owner_actor_id,
              metadata
            )
            values (
              :id,
              :tenant_id,
              :secret_uri,
              :scope,
              :name,
              :version,
              :status,
              :runner_injectable,
              cast(:allowed_consumers as jsonb),
              cast(:allowed_operations as jsonb),
              :owner_actor_id,
              cast(:metadata as jsonb)
            )
            """
        ),
        {
            "id": id,
            "tenant_id": tenant_id,
            "secret_uri": secret_uri or f"secret://sops/{scope}/{name}#{version}",
            "scope": scope,
            "name": name,
            "version": version,
            "status": status,
            "runner_injectable": runner_injectable,
            "allowed_consumers": allowed_consumers,
            "allowed_operations": allowed_operations,
            "owner_actor_id": owner_actor_id,
            "metadata": metadata,
        },
    )


async def _insert_capability_token(
    session: AsyncSession,
    *,
    id: UUID,
    tenant_id: int = 1,
    secret_ref_id: UUID = SECRET_REF_ONE_ID,
    issued_to_actor_id: UUID = TENANT_ONE_ACTOR_ID,
    token_hash: str = "0000000000000000000000000000000000000000000000000000000000000001",
    status: str = "issued",
    issued_run_id: UUID | None = None,
    expected_request_fingerprint: str = (
        "0000000000000000000000000000000000000000000000000000000000001234"
    ),
    created_at: datetime = datetime(2030, 1, 1, 0, 0, tzinfo=UTC),
    expires_at: datetime = datetime(2030, 1, 1, 0, 30, tzinfo=UTC),
    used_at: datetime | None = None,
    allowed_operations: str = '["provider.call"]',
    scope_constraint: str = '{"scope": "project"}',
    metadata: str = '{"rls_ready": true}',
) -> None:
    await session.execute(
        text(
            """
            insert into secret_capability_tokens (
              id,
              tenant_id,
              secret_ref_id,
              token_hash,
              allowed_operations,
              scope_constraint,
              issued_to_actor_id,
              issued_run_id,
              expected_request_fingerprint,
              expires_at,
              used_at,
              status,
              metadata,
              created_at
            )
            values (
              :id,
              :tenant_id,
              :secret_ref_id,
              :token_hash,
              cast(:allowed_operations as jsonb),
              cast(:scope_constraint as jsonb),
              :issued_to_actor_id,
              :issued_run_id,
              :expected_request_fingerprint,
              cast(:expires_at as timestamptz),
              cast(:used_at as timestamptz),
              :status,
              cast(:metadata as jsonb),
              cast(:created_at as timestamptz)
            )
            """
        ),
        {
            "id": id,
            "tenant_id": tenant_id,
            "secret_ref_id": secret_ref_id,
            "token_hash": token_hash,
            "issued_to_actor_id": issued_to_actor_id,
            "issued_run_id": issued_run_id,
            "expected_request_fingerprint": expected_request_fingerprint,
            "expires_at": expires_at,
            "used_at": used_at,
            "status": status,
            "allowed_operations": allowed_operations,
            "scope_constraint": scope_constraint,
            "metadata": metadata,
            "created_at": created_at,
        },
    )


async def _setup_tenant_one_secret(session: AsyncSession) -> None:
    await _reset_secret_tables(session)
    await _insert_tenant(session, 1, "tenant-one")
    await _insert_actor(
        session,
        tenant_id=1,
        actor_id=TENANT_ONE_ACTOR_ID,
        stable_actor_id="human:tenant-one",
    )
    await _insert_secret_ref(session, id=SECRET_REF_ONE_ID)
    await session.commit()


@pytest.mark.asyncio
async def test_secret_refs_runner_injectable_true_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                runner_injectable=True,
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_runner_injectable_false",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_duplicate_secret_uri(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await _insert_secret_ref(session, id=SECRET_REF_ONE_ID, status="deprecated")
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(session, id=SECRET_REF_TWO_ID, status="revoked")
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23505",
            constraint_name="secret_refs_uq_tenant_secret_uri",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_duplicate_scope_name_version(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await _insert_secret_ref(session, id=SECRET_REF_ONE_ID, status="deprecated")
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(session, id=SECRET_REF_TWO_ID, status="revoked")
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23505",
            constraint_name=(
                "secret_refs_uq_tenant_scope_name_version",
                "secret_refs_uq_tenant_secret_uri",
            ),
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_two_active_rows_for_same_scope_name(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await _insert_secret_ref(session, id=SECRET_REF_ONE_ID, version="v1", status="active")
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(session, id=SECRET_REF_TWO_ID, version="v2", status="active")
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23505",
            constraint_name="secret_refs_one_active_per_name",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_two_pending_rows_for_same_scope_name(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await _insert_secret_ref(session, id=SECRET_REF_ONE_ID, version="v1", status="pending")
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(session, id=SECRET_REF_TWO_ID, version="v2", status="pending")
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23505",
            constraint_name="secret_refs_one_pending_per_name",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_allow_one_active_and_one_pending_for_same_scope_name(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await _insert_secret_ref(session, id=SECRET_REF_ONE_ID, version="v1", status="active")
        await _insert_secret_ref(session, id=SECRET_REF_TWO_ID, version="v2", status="pending")
        await session.commit()

        row_count = await session.scalar(
            text(
                """
                select count(*)
                from secret_refs
                where tenant_id = 1
                  and scope = 'project'
                  and name = 'provider-openai'
                """
            )
        )

    assert row_count == 2


@pytest.mark.asyncio
async def test_secret_refs_status_rejects_unknown_value(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(session, id=SECRET_REF_ONE_ID, status="enabled")
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_status",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_uri_format_rejects_invalid_reference(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                name="provider.openai",
                secret_uri="secret://sops/project/provider.openai#v1",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_secret_uri_format",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_accept_p0_scope_uri(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )

        await _insert_secret_ref(
            session,
            id=SECRET_REF_ONE_ID,
            scope="p0",
            name="dev-login-token",
            version="v1",
            secret_uri="secret://sops/p0/dev-login-token#v1",
        )
        await session.commit()

        row_count = await session.scalar(
            text(
                """
                select count(*)
                from secret_refs
                where tenant_id = 1
                  and secret_uri = 'secret://sops/p0/dev-login-token#v1'
                """
            )
        )

    assert row_count == 1


@pytest.mark.asyncio
async def test_secret_refs_uri_format_rejects_unknown_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                scope="cluster",
                name="secret",
                secret_uri="secret://sops/cluster/secret#v1",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name=("secret_refs_ck_secret_uri_format", "secret_refs_ck_scope"),
        )
        assert "secret_refs_ck_secret_uri_components_match" not in str(exc_info.value)
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_uri_components_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                scope="project",
                name="provider-openai",
                version="v1",
                secret_uri="secret://sops/repo/provider-openai#v1",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_secret_uri_components_match",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_metadata_with_raw_secret_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                metadata='{"rls_ready": true, "raw_secret": "leaked"}',
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_metadata_no_raw_secret",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_nested_metadata_with_raw_secret(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                metadata='{"rls_ready": true, "credentials": {"api_key": "leak"}}',
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_metadata_no_raw_secret",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_deeply_nested_metadata_with_api_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                metadata='{"rls_ready": true, "a": {"b": {"api_key": "leak"}}}',
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_metadata_no_raw_secret",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_metadata_with_token_top_level_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                metadata='{"rls_ready": true, "token": "leaked"}',
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_metadata_no_raw_secret",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_metadata_with_raw_value_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                metadata='{"rls_ready": true, "raw_value": "leaked"}',
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_metadata_no_raw_secret",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_active_with_empty_allowlist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                allowed_consumers="[]",
                allowed_operations="[]",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_active_allowlist_nonempty",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_allowed_consumers_root_object(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                status="pending",
                allowed_consumers='{"foo": "bar"}',
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_allowlist_jsonb_arrays",
        )
        assert "SQL/JSON" not in str(exc_info.value)
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_allowed_operations_root_null(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                status="pending",
                allowed_operations="null",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_allowlist_jsonb_arrays",
        )
        assert "SQL/JSON" not in str(exc_info.value)
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_allowed_consumers_with_non_string_element(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                allowed_consumers="[null]",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_allowed_consumers_string_elements",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_allowed_consumers_with_number_element(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                allowed_consumers="[123]",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_allowed_consumers_string_elements",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_allowed_consumers_with_object_element(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                allowed_consumers='["api:provider_adapter", {"unexpected": true}]',
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_allowed_consumers_string_elements",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_reject_allowed_operations_with_non_string_element(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                id=SECRET_REF_ONE_ID,
                allowed_operations="[42]",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_refs_ck_allowed_operations_string_elements",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_refs_accept_pending_with_empty_allowlist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )

        await _insert_secret_ref(
            session,
            id=SECRET_REF_ONE_ID,
            status="pending",
            allowed_consumers="[]",
            allowed_operations="[]",
        )
        await session.commit()

        row_count = await session.scalar(
            text(
                """
                select count(*)
                from secret_refs
                where tenant_id = 1
                  and id = :secret_ref_id
                """
            ),
            {"secret_ref_id": SECRET_REF_ONE_ID},
        )

    assert row_count == 1


@pytest.mark.asyncio
async def test_capability_tokens_reject_duplicate_token_hash_within_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        await _insert_capability_token(session, id=TOKEN_ONE_ID)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_TWO_ID,
                expected_request_fingerprint=(
                    "0000000000000000000000000000000000000000000000000000000000005678"
                ),
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23505",
            constraint_name="secret_capability_tokens_uq_tenant_token_hash",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_non_sha256_token_hash(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                token_hash="raw-token-value",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_token_hash_format",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_non_sha256_fingerprint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                expected_request_fingerprint="caller-supplied-fingerprint",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_expected_request_fingerprint_format",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_metadata_with_raw_token_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                metadata='{"rls_ready": true, "raw_token": "leaked"}',
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_metadata_no_raw_secret",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_nested_metadata_with_raw_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                metadata='{"rls_ready": true, "context": {"raw_token": "leaked"}}',
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_metadata_no_raw_secret",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_deeply_nested_metadata_with_raw_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                metadata='{"rls_ready": true, "a": {"b": {"raw_token": "leak"}}}',
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_metadata_no_raw_secret",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_empty_allowed_operations(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                allowed_operations="[]",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_allowed_operations_nonempty_array",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_allowed_operations_root_string(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                allowed_operations='"foo"',
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_allowed_operations_nonempty_array",
        )
        assert "SQL/JSON" not in str(exc_info.value)
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_allowed_operations_with_non_string_element(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                allowed_operations="[null]",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_allowed_operations_string_elements",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_scope_constraint_not_object(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                scope_constraint="[]",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_scope_constraint_jsonb_object",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_status_rejects_unknown_value(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(session, id=TOKEN_ONE_ID, status="available")
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_status",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_expires_at_below_ttl_bounds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                created_at=datetime(2030, 1, 1, 0, 0, tzinfo=UTC),
                expires_at=datetime(2030, 1, 1, 0, 0, tzinfo=UTC),
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_expires_within_ttl_bounds",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_expires_at_above_ttl_bounds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                created_at=datetime(2030, 1, 1, 0, 0, tzinfo=UTC),
                expires_at=datetime(2030, 1, 1, 1, 0, tzinfo=UTC),
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_expires_within_ttl_bounds",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_accept_expires_at_within_ttl_bounds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        await _insert_capability_token(
            session,
            id=TOKEN_ONE_ID,
            created_at=datetime(2030, 1, 1, 0, 0, tzinfo=UTC),
            expires_at=datetime(2030, 1, 1, 0, 15, tzinfo=UTC),
        )
        await session.commit()

        row_count = await session.scalar(
            text(
                """
                select count(*)
                from secret_capability_tokens
                where tenant_id = 1
                  and id = :token_id
                """
            ),
            {"token_id": TOKEN_ONE_ID},
        )

    assert row_count == 1


@pytest.mark.asyncio
async def test_capability_tokens_accept_expires_at_at_lower_ttl_bound(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        await _insert_capability_token(
            session,
            id=TOKEN_ONE_ID,
            created_at=datetime(2030, 1, 1, 0, 0, tzinfo=UTC),
            expires_at=datetime(2030, 1, 1, 0, 5, tzinfo=UTC),
        )
        await session.commit()

        row_count = await session.scalar(
            text(
                """
                select count(*)
                from secret_capability_tokens
                where tenant_id = 1
                  and id = :token_id
                """
            ),
            {"token_id": TOKEN_ONE_ID},
        )

    assert row_count == 1


@pytest.mark.asyncio
async def test_capability_tokens_accept_expires_at_at_upper_ttl_bound(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        await _insert_capability_token(
            session,
            id=TOKEN_ONE_ID,
            created_at=datetime(2030, 1, 1, 0, 0, tzinfo=UTC),
            expires_at=datetime(2030, 1, 1, 0, 30, tzinfo=UTC),
        )
        await session.commit()

        row_count = await session.scalar(
            text(
                """
                select count(*)
                from secret_capability_tokens
                where tenant_id = 1
                  and id = :token_id
                """
            ),
            {"token_id": TOKEN_ONE_ID},
        )

    assert row_count == 1


@pytest.mark.asyncio
async def test_capability_tokens_reject_used_at_with_issued_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                status="issued",
                used_at=datetime(2030, 1, 1, 0, 1, tzinfo=UTC),
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_used_at_status",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_used_status_with_null_used_at(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                status="used",
                used_at=None,
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_used_at_status",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_reject_redeeming_status_with_null_used_at(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                status="redeeming",
                used_at=None,
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="secret_capability_tokens_ck_used_at_status",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_capability_tokens_accept_expired_status_with_null_used_at(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_tenant_one_secret(session)

        await _insert_capability_token(
            session,
            id=TOKEN_ONE_ID,
            status="expired",
            used_at=None,
        )
        await session.commit()

        row_count = await session.scalar(
            text(
                """
                select count(*)
                from secret_capability_tokens
                where tenant_id = 1
                  and id = :token_id
                  and status = 'expired'
                """
            ),
            {"token_id": TOKEN_ONE_ID},
        )

    assert row_count == 1


@pytest.mark.asyncio
async def test_capability_tokens_reject_cross_tenant_secret_ref_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_secret_tables(session)
        await _insert_tenant(session, 1, "tenant-one")
        await _insert_tenant(session, 2, "tenant-two")
        await _insert_actor(
            session,
            tenant_id=1,
            actor_id=TENANT_ONE_ACTOR_ID,
            stable_actor_id="human:tenant-one",
        )
        await _insert_actor(
            session,
            tenant_id=2,
            actor_id=TENANT_TWO_ACTOR_ID,
            stable_actor_id="human:tenant-two",
        )
        await _insert_secret_ref(session, id=SECRET_REF_ONE_ID)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                id=TOKEN_ONE_ID,
                tenant_id=2,
                secret_ref_id=SECRET_REF_ONE_ID,
                issued_to_actor_id=TENANT_TWO_ACTOR_ID,
                token_hash="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="secret_capability_tokens_secret_ref_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_secret_tables_do_not_have_raw_secret_or_raw_token_columns(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                select table_name, column_name
                from information_schema.columns
                where table_schema = 'public'
                  and table_name in ('secret_refs', 'secret_capability_tokens')
                """
            )
        )

    columns_by_table: dict[str, set[str]] = {
        "secret_refs": set(),
        "secret_capability_tokens": set(),
    }
    for row in result.mappings():
        columns_by_table[str(row["table_name"])].add(str(row["column_name"]))

    assert columns_by_table["secret_refs"].isdisjoint(PROHIBITED_SECRET_COLUMNS)
    assert columns_by_table["secret_capability_tokens"].isdisjoint(PROHIBITED_SECRET_COLUMNS)
    assert "expected_request_fingerprint" in columns_by_table["secret_capability_tokens"]

