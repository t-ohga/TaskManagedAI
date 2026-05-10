from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.project import Project
from backend.app.db.models.tenant import Tenant
from backend.app.db.session import create_engine
from backend.app.repositories.actor import ActorRepository
from backend.app.repositories.project import ProjectRepository
from backend.app.repositories.tenant import TenantRepository

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ONE_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000101")
TENANT_TWO_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000102")
TENANT_ONE_CREATED_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000103")
TENANT_ONE_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000201")
TENANT_TWO_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000202")
TENANT_ONE_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000401")
TENANT_TWO_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000402")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-repository-tests",
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
            raise AssertionError("Repository tests require a reachable test database.") from exc
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


async def _reset_core_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate repositories, projects, workspaces, principals, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_project_fixture(
    session: AsyncSession,
    *,
    tenant_id: int,
    tenant_name: str,
    owner_actor_id: UUID,
    actor_stable_id: str,
    workspace_id: UUID,
    workspace_slug: str,
    workspace_name: str,
    project_id: UUID,
    project_slug: str,
    project_name: str,
) -> None:
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (:tenant_id, :tenant_name, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"tenant_id": tenant_id, "tenant_name": tenant_name},
    )
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
              :owner_actor_id,
              :tenant_id,
              'human',
              :actor_stable_id,
              :actor_display_name,
              null,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "owner_actor_id": owner_actor_id,
            "tenant_id": tenant_id,
            "actor_stable_id": actor_stable_id,
            "actor_display_name": f"{tenant_name} Owner",
        },
    )
    await session.execute(
        text(
            """
            insert into workspaces (
              id,
              tenant_id,
              slug,
              name,
              owner_actor_id,
              metadata
            )
            values (
              :workspace_id,
              :tenant_id,
              :workspace_slug,
              :workspace_name,
              :owner_actor_id,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "workspace_id": workspace_id,
            "tenant_id": tenant_id,
            "workspace_slug": workspace_slug,
            "workspace_name": workspace_name,
            "owner_actor_id": owner_actor_id,
        },
    )
    await session.execute(
        text(
            """
            insert into projects (
              id,
              tenant_id,
              workspace_id,
              slug,
              name,
              status,
              policy_profile,
              metadata
            )
            values (
              :project_id,
              :tenant_id,
              :workspace_id,
              :project_slug,
              :project_name,
              'active',
              'default',
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "project_id": project_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "project_slug": project_slug,
            "project_name": project_name,
        },
    )


async def _insert_two_tenant_project_fixtures(session: AsyncSession) -> None:
    await _insert_project_fixture(
        session,
        tenant_id=1,
        tenant_name="tenant-one",
        owner_actor_id=TENANT_ONE_ACTOR_ID,
        actor_stable_id="human:default",
        workspace_id=TENANT_ONE_WORKSPACE_ID,
        workspace_slug="workspace-one",
        workspace_name="workspace-one",
        project_id=TENANT_ONE_PROJECT_ID,
        project_slug="project-one",
        project_name="project-one",
    )
    await _insert_project_fixture(
        session,
        tenant_id=2,
        tenant_name="tenant-two",
        owner_actor_id=TENANT_TWO_ACTOR_ID,
        actor_stable_id="human:default",
        workspace_id=TENANT_TWO_WORKSPACE_ID,
        workspace_slug="workspace-two",
        workspace_name="workspace-two",
        project_id=TENANT_TWO_PROJECT_ID,
        project_slug="project-two",
        project_name="project-two",
    )


def _compile_sql(statement: Any) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_base_repository_get_requires_tenant_id_argument() -> None:
    repository = ProjectRepository(cast(AsyncSession, object()))

    with pytest.raises(TypeError):
        repository.get(id=TENANT_ONE_PROJECT_ID)  # type: ignore[call-arg]


def test_base_repository_list_requires_tenant_id_argument() -> None:
    repository = ProjectRepository(cast(AsyncSession, object()))

    with pytest.raises(TypeError):
        repository.list()  # type: ignore[call-arg]


def test_base_repository_statements_include_tenant_id_predicates() -> None:
    repository = ProjectRepository(cast(AsyncSession, object()))

    list_sql = _compile_sql(repository.statement_for_list(tenant_id=1))
    update_sql = _compile_sql(
        repository.statement_for_update(
            tenant_id=1,
            id=TENANT_ONE_PROJECT_ID,
            payload={"name": "updated-name"},
        )
    )
    delete_sql = _compile_sql(
        repository.statement_for_delete(
            tenant_id=1,
            id=TENANT_ONE_PROJECT_ID,
        )
    )

    assert "WHERE projects.tenant_id = 1" in list_sql
    assert "WHERE projects.tenant_id = 1" in update_sql
    assert "WHERE projects.tenant_id = 1" in delete_sql


@pytest.mark.asyncio
async def test_project_repository_get_does_not_return_cross_tenant_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_core_tables(session)
        await _insert_two_tenant_project_fixtures(session)

        repository = ProjectRepository(session)
        cross_tenant_result = await repository.get(tenant_id=1, id=TENANT_TWO_PROJECT_ID)

    assert cross_tenant_result is None


@pytest.mark.asyncio
async def test_project_repository_list_excludes_cross_tenant_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_core_tables(session)
        await _insert_two_tenant_project_fixtures(session)

        repository = ProjectRepository(session)
        tenant_one_projects = await repository.list(tenant_id=1)

    assert [project.id for project in tenant_one_projects] == [TENANT_ONE_PROJECT_ID]
    assert [project.tenant_id for project in tenant_one_projects] == [1]


@pytest.mark.asyncio
async def test_project_repository_create_injects_matching_tenant_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_core_tables(session)
        await _insert_project_fixture(
            session,
            tenant_id=1,
            tenant_name="tenant-one",
            owner_actor_id=TENANT_ONE_ACTOR_ID,
            actor_stable_id="human:default",
            workspace_id=TENANT_ONE_WORKSPACE_ID,
            workspace_slug="workspace-one",
            workspace_name="workspace-one",
            project_id=TENANT_ONE_PROJECT_ID,
            project_slug="project-one",
            project_name="project-one",
        )

        repository = ProjectRepository(session)
        created = await repository.create(
            tenant_id=1,
            payload={
                "id": TENANT_ONE_CREATED_PROJECT_ID,
                "workspace_id": TENANT_ONE_WORKSPACE_ID,
                "slug": "created-project",
                "name": "created-project",
                "status": "active",
                "policy_profile": None,
                "metadata": {"rls_ready": True, "source": "repository-test"},
            },
        )

    assert created.tenant_id == 1
    assert created.id == TENANT_ONE_CREATED_PROJECT_ID
    assert created.workspace_id == TENANT_ONE_WORKSPACE_ID
    assert created.slug == "created-project"
    assert created.metadata_["rls_ready"] is True


@pytest.mark.asyncio
async def test_project_repository_create_rejects_conflicting_payload_tenant_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        repository = ProjectRepository(session)

        with pytest.raises(ValueError, match="payload tenant_id must match"):
            await repository.create(
                tenant_id=1,
                payload={
                    "tenant_id": 2,
                    "workspace_id": TENANT_ONE_WORKSPACE_ID,
                    "slug": "bad-project",
                    "name": "bad-project",
                },
            )


@pytest.mark.asyncio
async def test_project_repository_update_does_not_modify_cross_tenant_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_core_tables(session)
        await _insert_two_tenant_project_fixtures(session)

        repository = ProjectRepository(session)
        updated = await repository.update(
            tenant_id=1,
            id=TENANT_TWO_PROJECT_ID,
            payload={"name": "should-not-change"},
        )
        tenant_two_project = await session.scalar(
            select(Project).where(Project.id == TENANT_TWO_PROJECT_ID)
        )

    assert updated is None
    assert tenant_two_project is not None
    assert tenant_two_project.tenant_id == 2
    assert tenant_two_project.name == "project-two"


@pytest.mark.asyncio
async def test_project_repository_delete_does_not_delete_cross_tenant_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_core_tables(session)
        await _insert_two_tenant_project_fixtures(session)

        repository = ProjectRepository(session)
        deleted_count = await repository.delete(tenant_id=1, id=TENANT_TWO_PROJECT_ID)
        tenant_two_project_count = await session.scalar(
            select(func.count(Project.id)).where(Project.id == TENANT_TWO_PROJECT_ID)
        )

    assert deleted_count == 0
    assert tenant_two_project_count == 1


@pytest.mark.asyncio
async def test_actor_repository_get_human_default_returns_seeded_actor(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_core_tables(session)
        await _insert_project_fixture(
            session,
            tenant_id=1,
            tenant_name="tenant-one",
            owner_actor_id=TENANT_ONE_ACTOR_ID,
            actor_stable_id="human:default",
            workspace_id=TENANT_ONE_WORKSPACE_ID,
            workspace_slug="workspace-one",
            workspace_name="workspace-one",
            project_id=TENANT_ONE_PROJECT_ID,
            project_slug="project-one",
            project_name="project-one",
        )

        repository = ActorRepository(session)
        actor = await repository.get_human_default(tenant_id=1)

    assert actor.id == TENANT_ONE_ACTOR_ID
    assert actor.tenant_id == 1
    assert actor.actor_type == "human"
    assert actor.actor_id == "human:default"


@pytest.mark.asyncio
async def test_tenant_repository_get_returns_none_for_missing_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await _reset_core_tables(session)
        repository = TenantRepository(session)
        missing_tenant = await repository.get(tenant_id=999)

    assert missing_tenant is None


@pytest.mark.asyncio
async def test_tenant_repository_create_duplicate_raises_integrity_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_core_tables(session)
        await session.commit()

        repository = TenantRepository(session)
        created = await repository.create(
            tenant_id=1,
            payload={"name": "tenant-one", "metadata": {"rls_ready": True}},
        )
        await session.commit()

        # session.rollback() は expire_on_commit=False を無視して instance attributes を
        # 必ず expire させる SQLAlchemy 仕様 (https://sqlalche.me/e/20/bhk3) のため、
        # rollback 前に created の identity attrs を local variable に capture する。
        # 後続 assert は detached instance を参照しないので DetachedInstanceError を回避。
        created_kind: type[Tenant] = type(created)
        created_id = created.id
        created_name = created.name

        with pytest.raises(IntegrityError):
            await repository.create(
                tenant_id=1,
                payload={"name": "tenant-one-duplicate", "metadata": {"rls_ready": True}},
            )
            await session.commit()

        await session.rollback()

    assert created_kind is Tenant
    assert created_id == 1
    assert created_name == "tenant-one"

