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
from backend.app.db.app_role import assert_tenant_context, set_tenant_context
from backend.app.db.models.secret_capability_token import SecretCapabilityToken
from backend.app.db.session import create_engine
from backend.app.repositories.ticket import TicketRepository

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ONE_ACTOR_ID = UUID("00000000-0000-4000-8000-000000002001")
TENANT_TWO_ACTOR_ID = UUID("00000000-0000-4000-8000-000000002002")
TENANT_ONE_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000002011")
TENANT_TWO_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000002012")
TENANT_ONE_PROJECT_ID = UUID("00000000-0000-4000-8000-000000002021")
TENANT_TWO_PROJECT_ID = UUID("00000000-0000-4000-8000-000000002022")
TENANT_ONE_SECOND_PROJECT_ID = UUID("00000000-0000-4000-8000-000000002023")
TENANT_ONE_REPOSITORY_ID = UUID("00000000-0000-4000-8000-000000002031")
TENANT_TWO_REPOSITORY_ID = UUID("00000000-0000-4000-8000-000000002032")
TENANT_ONE_SECOND_REPOSITORY_ID = UUID("00000000-0000-4000-8000-000000002033")
TENANT_ONE_TICKET_ID = UUID("00000000-0000-4000-8000-000000002041")
TENANT_TWO_TICKET_ID = UUID("00000000-0000-4000-8000-000000002042")
CROSS_TENANT_TICKET_ID = UUID("00000000-0000-4000-8000-000000002043")
TENANT_ONE_SECRET_REF_ID = UUID("00000000-0000-4000-8000-000000002051")
TENANT_TWO_SECRET_REF_ID = UUID("00000000-0000-4000-8000-000000002052")
CROSS_TENANT_SECRET_REF_ID = UUID("00000000-0000-4000-8000-000000002053")
CROSS_TENANT_TOKEN_ID = UUID("00000000-0000-4000-8000-000000002061")
EXPECTED_FINGERPRINT_COLUMN = "expected_request_" "fingerprint"


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-tenant-isolation-tests",
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
            raise AssertionError("Tenant isolation tests require a reachable test database.") from exc
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

        if current.__cause__ is not None:
            queue.append(current.__cause__)

        if current.__context__ is not None:
            queue.append(current.__context__)

        for arg in getattr(current, "args", ()):
            if isinstance(arg, BaseException):
                queue.append(arg)

    return None


def _assert_integrity_error(
    error: IntegrityError,
    *,
    sqlstate: str,
    constraint_name: str,
) -> None:
    assert _sqlstate(error) == sqlstate
    actual_constraint_name = (
        getattr(error.orig, 'constraint_name', None)
        or getattr(getattr(error.orig, '__cause__', None), 'constraint_name', None)
    )
    assert actual_constraint_name == constraint_name


async def _reset_tables(session: AsyncSession) -> None:
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
              id, tenant_id, actor_type, actor_id, display_name, auth_context_hash, metadata
            )
            values (
              :actor_id, :tenant_id, 'human', :stable_actor_id, :display_name,
              :auth_context_hash, '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "actor_id": actor_id,
            "tenant_id": tenant_id,
            "stable_actor_id": stable_actor_id,
            "display_name": f"Tenant {tenant_id} Actor",
            "auth_context_hash": f"tenant-{tenant_id}-auth-context",
        },
    )


async def _insert_workspace(
    session: AsyncSession,
    *,
    tenant_id: int,
    workspace_id: UUID,
    owner_actor_id: UUID,
    slug: str,
) -> None:
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (
              :workspace_id, :tenant_id, :slug, :slug, :owner_actor_id,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "workspace_id": workspace_id,
            "tenant_id": tenant_id,
            "slug": slug,
            "owner_actor_id": owner_actor_id,
        },
    )


async def _insert_project(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    workspace_id: UUID,
    slug: str,
) -> None:
    await session.execute(
        text(
            """
            insert into projects (
              id, tenant_id, workspace_id, slug, name, status, policy_profile, metadata
            )
            values (
              :project_id, :tenant_id, :workspace_id, :slug, :slug, 'active',
              'default', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "project_id": project_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "slug": slug,
        },
    )


async def _insert_repository(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    repository_id: UUID,
    external_id: str,
) -> None:
    await session.execute(
        text(
            """
            insert into repositories (
              id, tenant_id, project_id, provider, external_id, owner_name, repo_name,
              default_branch, metadata
            )
            values (
              :repository_id, :tenant_id, :project_id, 'github', :external_id,
              'tenant-owner', :external_id, 'main', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "repository_id": repository_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "external_id": external_id,
        },
    )


async def _insert_ticket(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: UUID,
    ticket_id: UUID,
    created_by_actor_id: UUID,
    slug: str,
    repository_id: UUID | None = None,
) -> None:
    await session.execute(
        text(
            """
            insert into tickets (
              id, tenant_id, project_id, repository_id, slug, title, status,
              created_by_actor_id, metadata
            )
            values (
              :ticket_id, :tenant_id, :project_id, :repository_id, :slug, :title,
              'open', :created_by_actor_id, '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "ticket_id": ticket_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "repository_id": repository_id,
            "slug": slug,
            "title": slug.replace("-", " ").title(),
            "created_by_actor_id": created_by_actor_id,
        },
    )


async def _insert_secret_ref(
    session: AsyncSession,
    *,
    secret_ref_id: UUID,
    tenant_id: int,
    owner_actor_id: UUID,
    name: str,
    version: str = "v1",
) -> None:
    await session.execute(
        text(
            """
            insert into secret_refs (
              id, tenant_id, secret_uri, scope, name, version, status,
              runner_injectable, allowed_consumers, allowed_operations,
              owner_actor_id, metadata
            )
            values (
              :secret_ref_id, :tenant_id, :secret_uri, 'project', :name, :version,
              'active', false, '["api:provider_adapter"]'::jsonb,
              '["provider.call"]'::jsonb, :owner_actor_id,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "secret_ref_id": secret_ref_id,
            "tenant_id": tenant_id,
            "secret_uri": f"secret://sops/project/{name}#{version}",
            "name": name,
            "version": version,
            "owner_actor_id": owner_actor_id,
        },
    )


async def _insert_capability_token(
    session: AsyncSession,
    *,
    token_id: UUID,
    tenant_id: int,
    secret_ref_id: UUID,
    issued_to_actor_id: UUID,
) -> None:
    token = SecretCapabilityToken(
        id=token_id,
        tenant_id=tenant_id,
        secret_ref_id=secret_ref_id,
        token_hash="1" * 64,
        allowed_operations=["provider.call"],
        scope_constraint={"scope": "project"},
        issued_to_actor_id=issued_to_actor_id,
        issued_run_id=None,
        expires_at=datetime(2030, 1, 1, 0, 30, tzinfo=UTC),
        status="issued",
        metadata_={"rls_ready": True},
        created_at=datetime(2030, 1, 1, 0, 0, tzinfo=UTC),
    )
    setattr(token, EXPECTED_FINGERPRINT_COLUMN, "2" * 64)
    session.add(token)
    await session.flush()


async def _setup_two_tenants(session: AsyncSession) -> None:
    await _reset_tables(session)
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
    await _insert_workspace(
        session,
        tenant_id=1,
        workspace_id=TENANT_ONE_WORKSPACE_ID,
        owner_actor_id=TENANT_ONE_ACTOR_ID,
        slug="tenant-one-workspace",
    )
    await _insert_workspace(
        session,
        tenant_id=2,
        workspace_id=TENANT_TWO_WORKSPACE_ID,
        owner_actor_id=TENANT_TWO_ACTOR_ID,
        slug="tenant-two-workspace",
    )
    await _insert_project(
        session,
        tenant_id=1,
        project_id=TENANT_ONE_PROJECT_ID,
        workspace_id=TENANT_ONE_WORKSPACE_ID,
        slug="tenant-one-project",
    )
    await _insert_project(
        session,
        tenant_id=2,
        project_id=TENANT_TWO_PROJECT_ID,
        workspace_id=TENANT_TWO_WORKSPACE_ID,
        slug="tenant-two-project",
    )
    await _insert_repository(
        session,
        tenant_id=1,
        project_id=TENANT_ONE_PROJECT_ID,
        repository_id=TENANT_ONE_REPOSITORY_ID,
        external_id="tenant-one-repo",
    )
    await _insert_repository(
        session,
        tenant_id=2,
        project_id=TENANT_TWO_PROJECT_ID,
        repository_id=TENANT_TWO_REPOSITORY_ID,
        external_id="tenant-two-repo",
    )
    await _insert_ticket(
        session,
        tenant_id=1,
        project_id=TENANT_ONE_PROJECT_ID,
        ticket_id=TENANT_ONE_TICKET_ID,
        created_by_actor_id=TENANT_ONE_ACTOR_ID,
        slug="tenant-one-ticket",
    )
    await _insert_ticket(
        session,
        tenant_id=2,
        project_id=TENANT_TWO_PROJECT_ID,
        ticket_id=TENANT_TWO_TICKET_ID,
        created_by_actor_id=TENANT_TWO_ACTOR_ID,
        slug="tenant-two-ticket",
    )
    await _insert_secret_ref(
        session,
        secret_ref_id=TENANT_ONE_SECRET_REF_ID,
        tenant_id=1,
        owner_actor_id=TENANT_ONE_ACTOR_ID,
        name="tenant-one-provider",
    )
    await _insert_secret_ref(
        session,
        secret_ref_id=TENANT_TWO_SECRET_REF_ID,
        tenant_id=2,
        owner_actor_id=TENANT_TWO_ACTOR_ID,
        name="tenant-two-provider",
    )


@pytest.mark.asyncio
async def test_cross_tenant_ticket_select_returns_no_rows_through_repository(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _setup_two_tenants(session)
        await set_tenant_context(session, 1)

        repository = TicketRepository(session)
        cross_tenant_ticket = await repository.get_in_project(
            tenant_id=1,
            project_id=TENANT_TWO_PROJECT_ID,
            ticket_id=TENANT_TWO_TICKET_ID,
        )
        tenant_one_match_count = await session.scalar(
            text(
                """
                select count(*)
                from tickets
                where tenant_id = 1
                  and project_id = :project_id
                  and id = :ticket_id
                """
            ),
            {"project_id": TENANT_TWO_PROJECT_ID, "ticket_id": TENANT_TWO_TICKET_ID},
        )

    assert cross_tenant_ticket is None
    assert tenant_one_match_count == 0


@pytest.mark.asyncio
async def test_cross_tenant_delete_via_repository_returns_zero_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _setup_two_tenants(session)
        await set_tenant_context(session, 1)

        repository = TicketRepository(session)
        deleted_count = await repository.delete_in_project(
            tenant_id=1,
            project_id=TENANT_TWO_PROJECT_ID,
            ticket_id=TENANT_TWO_TICKET_ID,
        )
        tenant_two_ticket_count = await session.scalar(
            text("select count(*) from tickets where tenant_id = 2 and id = :ticket_id"),
            {"ticket_id": TENANT_TWO_TICKET_ID},
        )

    assert deleted_count == 0
    assert tenant_two_ticket_count == 1


@pytest.mark.asyncio
async def test_cross_tenant_delete_via_app_role_mismatch_raises_value_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _setup_two_tenants(session)
        await set_tenant_context(session, 1)

        repository = TicketRepository(session)
        with pytest.raises(ValueError, match="tenant context mismatch"):
            await repository.delete_in_project(
                tenant_id=2,
                project_id=TENANT_TWO_PROJECT_ID,
                ticket_id=TENANT_TWO_TICKET_ID,
            )


@pytest.mark.asyncio
async def test_assert_tenant_context_rejects_cross_tenant_select_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _setup_two_tenants(session)
        await set_tenant_context(session, 1)

        with pytest.raises(ValueError, match="tenant context mismatch"):
            await assert_tenant_context(session, 2)


@pytest.mark.asyncio
async def test_cross_tenant_secret_ref_owner_actor_fkey(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_two_tenants(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_secret_ref(
                session,
                secret_ref_id=CROSS_TENANT_SECRET_REF_ID,
                tenant_id=2,
                owner_actor_id=TENANT_ONE_ACTOR_ID,
                name="cross-tenant-owner",
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="secret_refs_owner_actor_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_cross_tenant_ticket_repository_fkey(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_two_tenants(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_ticket(
                session,
                tenant_id=1,
                project_id=TENANT_ONE_PROJECT_ID,
                ticket_id=CROSS_TENANT_TICKET_ID,
                created_by_actor_id=TENANT_ONE_ACTOR_ID,
                slug="cross-tenant-repository",
                repository_id=TENANT_TWO_REPOSITORY_ID,
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="tickets_repository_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_ticket_repository_project_fkey_rejects_same_tenant_cross_project_repository(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_two_tenants(session)
        await _insert_project(
            session,
            tenant_id=1,
            project_id=TENANT_ONE_SECOND_PROJECT_ID,
            workspace_id=TENANT_ONE_WORKSPACE_ID,
            slug="tenant-one-second-project",
        )
        await _insert_repository(
            session,
            tenant_id=1,
            project_id=TENANT_ONE_SECOND_PROJECT_ID,
            repository_id=TENANT_ONE_SECOND_REPOSITORY_ID,
            external_id="tenant-one-second-repo",
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_ticket(
                session,
                tenant_id=1,
                project_id=TENANT_ONE_PROJECT_ID,
                ticket_id=CROSS_TENANT_TICKET_ID,
                created_by_actor_id=TENANT_ONE_ACTOR_ID,
                slug="same-tenant-cross-project-repository",
                repository_id=TENANT_ONE_SECOND_REPOSITORY_ID,
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="tickets_repository_project_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_cross_tenant_audit_event_actor_insert_fails_by_actor_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_two_tenants(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            # audit_events.id は NOT NULL + server_default 無し。id を省略すると 23502
            # (NOT NULL violation) が先に fire し、目的の actor FK 違反 (23503) を検証できない。
            # uuid_generate_v4() で明示生成して FK check 経路まで到達させる。
            await session.execute(
                text(
                    """
                    insert into audit_events (
                      id, tenant_id, event_type, event_payload, actor_id, correlation_id
                    )
                    values (
                      uuid_generate_v4(), 1, 'tenant_boundary.cross_actor',
                      '{"rls_ready": true, "result": "blocked"}'::jsonb,
                      :actor_id, 'tenant-boundary-cross-actor'
                    )
                    """
                ),
                {"actor_id": TENANT_TWO_ACTOR_ID},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="audit_events_actor_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_cross_tenant_capability_token_secret_ref_insert_fails_by_secret_ref_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_two_tenants(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_capability_token(
                session,
                token_id=CROSS_TENANT_TOKEN_ID,
                tenant_id=1,
                secret_ref_id=TENANT_TWO_SECRET_REF_ID,
                issued_to_actor_id=TENANT_ONE_ACTOR_ID,
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="secret_capability_tokens_secret_ref_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_cross_tenant_update_partial_fk_mismatch_blocked(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Partial tenant moves leave project_id behind and fail by tickets_project_fkey."""
    async with session_factory() as session:
        await _setup_two_tenants(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    update tickets
                    set tenant_id = 2,
                        created_by_actor_id = :tenant_two_actor_id
                    where id = :ticket_id
                    """
                ),
                {
                    "tenant_two_actor_id": TENANT_TWO_ACTOR_ID,
                    "ticket_id": TENANT_ONE_TICKET_ID,
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="tickets_project_fkey",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_repository_update_rejects_cross_tenant_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _setup_two_tenants(session)
        await set_tenant_context(session, 1)

        repository = TicketRepository(session)
        with pytest.raises(ValueError, match="payload tenant_id must match"):
            await repository.update_in_project(
                tenant_id=1,
                project_id=TENANT_ONE_PROJECT_ID,
                ticket_id=TENANT_ONE_TICKET_ID,
                payload={
                    "tenant_id": 2,
                    "title": "should-not-cross-tenant",
                },
            )

        result = await session.execute(
            text(
                """
                select tenant_id, project_id::text as project_id, title
                from tickets
                where id = :ticket_id
                """
            ),
            {"ticket_id": TENANT_ONE_TICKET_ID},
        )
        row = result.one()

    assert row.tenant_id == 1
    assert row.project_id == str(TENANT_ONE_PROJECT_ID)
    assert row.title == "Tenant One Ticket"


@pytest.mark.asyncio
async def test_repository_update_rejects_cross_project_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _setup_two_tenants(session)
        await _insert_project(
            session,
            tenant_id=1,
            project_id=TENANT_ONE_SECOND_PROJECT_ID,
            workspace_id=TENANT_ONE_WORKSPACE_ID,
            slug="tenant-one-second-project",
        )
        await set_tenant_context(session, 1)

        repository = TicketRepository(session)
        with pytest.raises(ValueError, match="payload project_id must match"):
            await repository.update_in_project(
                tenant_id=1,
                project_id=TENANT_ONE_PROJECT_ID,
                ticket_id=TENANT_ONE_TICKET_ID,
                payload={
                    "project_id": TENANT_ONE_SECOND_PROJECT_ID,
                    "title": "should-not-cross-project",
                },
            )

        result = await session.execute(
            text(
                """
                select tenant_id, project_id::text as project_id, title
                from tickets
                where id = :ticket_id
                """
            ),
            {"ticket_id": TENANT_ONE_TICKET_ID},
        )
        row = result.one()

    assert row.tenant_id == 1
    assert row.project_id == str(TENANT_ONE_PROJECT_ID)
    assert row.title == "Tenant One Ticket"


@pytest.mark.asyncio
async def test_db_coordinated_move_p0_limitation_documents_repository_layer_enforcement(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """P0 FKs allow coordinated tenant/project/actor moves; repository payload guards block them."""
    async with session_factory.begin() as session:
        await _setup_two_tenants(session)

        update_result = await session.execute(
            text(
                """
                update tickets
                set tenant_id = 2,
                    project_id = :tenant_two_project_id,
                    created_by_actor_id = :tenant_two_actor_id
                where id = :ticket_id
                """
            ),
            {
                "tenant_two_project_id": TENANT_TWO_PROJECT_ID,
                "tenant_two_actor_id": TENANT_TWO_ACTOR_ID,
                "ticket_id": TENANT_ONE_TICKET_ID,
            },
        )
        assert update_result.rowcount == 1

        moved_result = await session.execute(
            text(
                """
                select tenant_id,
                       project_id::text as project_id,
                       created_by_actor_id::text as created_by_actor_id
                from tickets
                where id = :ticket_id
                """
            ),
            {"ticket_id": TENANT_ONE_TICKET_ID},
        )
        moved = moved_result.one()

        await set_tenant_context(session, 1)
        repository = TicketRepository(session)
        with pytest.raises(ValueError, match="payload tenant_id must match"):
            await repository.update_in_project(
                tenant_id=1,
                project_id=TENANT_ONE_PROJECT_ID,
                ticket_id=TENANT_ONE_TICKET_ID,
                payload={
                    "tenant_id": 2,
                    "project_id": TENANT_TWO_PROJECT_ID,
                    "created_by_actor_id": TENANT_TWO_ACTOR_ID,
                    "title": "should-not-coordinate-move",
                },
            )

    assert moved.tenant_id == 2
    assert moved.project_id == str(TENANT_TWO_PROJECT_ID)
    assert moved.created_by_actor_id == str(TENANT_TWO_ACTOR_ID)


@pytest.mark.asyncio
async def test_cross_tenant_actor_delete_blocked_by_restrict_fkey(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_two_tenants(session)
        await session.execute(text("delete from secret_refs where tenant_id = 1"))
        await session.execute(text("delete from tickets where tenant_id = 1"))
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text("delete from actors where tenant_id = 1 and id = :actor_id"),
                {"actor_id": TENANT_ONE_ACTOR_ID},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="workspaces_owner_actor_fkey",
        )
        await session.rollback()

