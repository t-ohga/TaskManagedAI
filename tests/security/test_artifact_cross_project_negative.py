"""AC-HARD-03 artifact-domain cross-project negative test.

Phase F-0 SP-012-7 must_ship 3 = research-domain test
(`test_research_cross_project_negative.py`、SP-010) と並ぶ artifact-domain
test。artifacts.project_id materialize (migration 0019) 後の composite FK
`(tenant_id, project_id, run_id) → agent_runs(tenant_id, project_id, id)` が
cross-project artifact reference を reject することを verify。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時
のみ実行。未起動なら skip (Mac local docker compose / CI Smoke 経由で実行)。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import CursorResult, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine

# Module-level skip: DB integration test は TASKMANAGEDAI_RUN_DB_TESTS=1 + test
# PostgreSQL container 起動時のみ実行 (Mac local docker compose / CI Smoke 経由)。
pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000044001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000044002")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000044003")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000044004")
RUN_A_ID = UUID("00000000-0000-4000-8000-000000044005")
RUN_B_ID = UUID("00000000-0000-4000-8000-000000044006")
ARTIFACT_A_ID = UUID("00000000-0000-4000-8000-000000044007")
ARTIFACT_B_ID = UUID("00000000-0000-4000-8000-000000044008")
CROSS_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000044009")
VALID_HASH_A = "a" * 64
VALID_HASH_B = "b" * 64
VALID_HASH_CROSS = "c" * 64


def _integration_settings() -> Settings:
    database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL)
    redis_url = os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL)
    return Settings(
        database_url=database_url,
        redis_url=redis_url,
        dev_login_cookie_secret="test-cookie-secret-for-artifact-cross-project",
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
            raise AssertionError(
                "Artifact cross-project tests require PostgreSQL."
            ) from exc
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


def _constraint_name(error: BaseException) -> str | None:
    return (
        getattr(error, "constraint_name", None)
        or getattr(getattr(error, "orig", None), "constraint_name", None)
        or getattr(
            getattr(getattr(error, "orig", None), "__cause__", None),
            "constraint_name",
            None,
        )
    )


def _assert_integrity_error(
    error: IntegrityError,
    *,
    sqlstate: str,
    constraint_name: str,
) -> None:
    assert _sqlstate(error) == sqlstate
    assert _constraint_name(error) == constraint_name


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate audit_events, agent_run_events, artifacts, agent_runs,
              projects, workspaces, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_fixtures(session: AsyncSession) -> None:
    """2 project (A/B) + agent_run (A/B) + artifact (A/B) fixture を投入。"""
    await session.execute(
        text(
            "insert into tenants (id, name, metadata) "
            "values (1, 'tenant-one', '{\"rls_ready\": true}'::jsonb)"
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:actor_id, 1, 'human', 'human:artifact', 'Artifact Actor',
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'workspace', 'workspace', :actor_id,
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:project_a_id, 1, :workspace_id, 'project-a', 'project-a', 'active',
                '{"rls_ready": true}'::jsonb),
              (:project_b_id, 1, :workspace_id, 'project-b', 'project-b', 'active',
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "workspace_id": WORKSPACE_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into agent_runs (
              id, tenant_id, project_id, status
            )
            values
              (:run_a_id, 1, :project_a_id, 'queued'),
              (:run_b_id, 1, :project_b_id, 'queued')
            """
        ),
        {
            "run_a_id": RUN_A_ID,
            "run_b_id": RUN_B_ID,
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into artifacts (
              id, tenant_id, run_id, project_id, kind, content_hash, content_jsonb,
              payload_data_class, trust_level, exportable
            )
            values
              (:artifact_a_id, 1, :run_a_id, :project_a_id, 'plan', :hash_a,
                '{"summary":"redacted"}'::jsonb, 'internal', 'untrusted_content', true),
              (:artifact_b_id, 1, :run_b_id, :project_b_id, 'plan', :hash_b,
                '{"summary":"redacted"}'::jsonb, 'internal', 'untrusted_content', true)
            """
        ),
        {
            "artifact_a_id": ARTIFACT_A_ID,
            "artifact_b_id": ARTIFACT_B_ID,
            "run_a_id": RUN_A_ID,
            "run_b_id": RUN_B_ID,
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "hash_a": VALID_HASH_A,
            "hash_b": VALID_HASH_B,
        },
    )
    await session.commit()


@pytest.mark.asyncio
async def test_artifact_insert_cross_project_run_rejects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """artifact INSERT で run_id が project_a に属するのに project_id=project_b で指定 → reject.

    composite FK artifacts_run_project_fkey
    `(tenant_id, project_id, run_id) → agent_runs(tenant_id, project_id, id)` 違反。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into artifacts (
                      id, tenant_id, run_id, project_id, kind, content_hash,
                      content_jsonb, payload_data_class, trust_level, exportable
                    )
                    values (
                      :artifact_id, 1, :run_a_id, :project_b_id, 'plan',
                      :hash_cross, '{"summary":"redacted"}'::jsonb, 'internal',
                      'untrusted_content', true
                    )
                    """
                ),
                {
                    "artifact_id": CROSS_ARTIFACT_ID,
                    "run_a_id": RUN_A_ID,
                    "project_b_id": PROJECT_B_ID,
                    "hash_cross": VALID_HASH_CROSS,
                },
            )
            await session.commit()
        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",  # foreign_key_violation
            constraint_name="artifacts_run_project_fkey",
        )


@pytest.mark.asyncio
async def test_artifact_insert_invalid_project_rejects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """artifact INSERT で project_id が tenant 内に存在しない UUID → reject.

    composite FK artifacts_project_fkey
    `(tenant_id, project_id) → projects(tenant_id, id)` 違反。
    """
    nonexistent_project_id = UUID("00000000-0000-4000-8000-0000000440aa")
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    insert into artifacts (
                      id, tenant_id, run_id, project_id, kind, content_hash,
                      content_jsonb, payload_data_class, trust_level, exportable
                    )
                    values (
                      :artifact_id, 1, :run_a_id, :nonexistent_project_id, 'plan',
                      :hash_cross, '{"summary":"redacted"}'::jsonb, 'internal',
                      'untrusted_content', true
                    )
                    """
                ),
                {
                    "artifact_id": CROSS_ARTIFACT_ID,
                    "run_a_id": RUN_A_ID,
                    "nonexistent_project_id": nonexistent_project_id,
                    "hash_cross": VALID_HASH_CROSS,
                },
            )
            await session.commit()
        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",  # foreign_key_violation
            constraint_name="artifacts_project_fkey",
        )


@pytest.mark.asyncio
async def test_artifact_select_cross_project_returns_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """artifact SELECT で project_b の query では project_a の artifact が見えない.

    artifacts_uq_tenant_project_id unique constraint と
    artifacts_idx_tenant_project_created index による project boundary
    direct query を verify。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        # project_b では artifact_b のみ visible (artifact_a は cross-project 不可視)
        result_b = await session.execute(
            text(
                """
                select id from artifacts
                where tenant_id = 1 and project_id = :project_b_id
                order by id
                """
            ),
            {"project_b_id": PROJECT_B_ID},
        )
        rows_b = [row[0] for row in result_b.all()]
        assert rows_b == [ARTIFACT_B_ID], (
            f"project_b query で project_a の artifact が visible: {rows_b}"
        )

        # project_a では artifact_a のみ visible
        result_a = await session.execute(
            text(
                """
                select id from artifacts
                where tenant_id = 1 and project_id = :project_a_id
                order by id
                """
            ),
            {"project_a_id": PROJECT_A_ID},
        )
        rows_a = [row[0] for row in result_a.all()]
        assert rows_a == [ARTIFACT_A_ID], (
            f"project_a query で project_b の artifact が visible: {rows_a}"
        )


@pytest.mark.asyncio
async def test_artifact_update_cross_project_run_rejects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """artifact UPDATE で project_id を別 project に変更 → reject.

    artifact は immutable (statement_for_update NotImplementedError) だが、
    DB 層 raw SQL UPDATE 試行で composite FK 違反を verify (defense-in-depth)。
    artifact_a の project_id を project_b に UPDATE 試行 → run_id mismatch で
    artifacts_run_project_fkey 違反。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    """
                    update artifacts
                    set project_id = :project_b_id
                    where tenant_id = 1 and id = :artifact_a_id
                    """
                ),
                {
                    "artifact_a_id": ARTIFACT_A_ID,
                    "project_b_id": PROJECT_B_ID,
                },
            )
            await session.commit()
        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",  # foreign_key_violation
            constraint_name="artifacts_run_project_fkey",
        )


@pytest.mark.asyncio
async def test_artifact_delete_cross_project_rejects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """artifact DELETE は append-only (statement_for_delete NotImplementedError) だが、
    DB 層 raw SQL DELETE で cross-tenant negative も verify。

    project_id 経由の tenant boundary direct query で削除 attempt が tenant_id mismatch
    なら 0 row affected (silent skip、これは tenant invariant の正常動作)、
    application 層は repository contract で statement_for_delete NotImplementedError raise。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)

    async with session_factory() as session:
        # tenant_id mismatch DELETE は 0 rows affected (silent skip、tenant boundary)
        result = await session.execute(
            text(
                """
                delete from artifacts
                where tenant_id = 99 and project_id = :project_a_id and id = :artifact_a_id
                """
            ),
            {
                "artifact_a_id": ARTIFACT_A_ID,
                "project_a_id": PROJECT_A_ID,
            },
        )
        # CursorResult.rowcount for DML statements
        assert isinstance(result, CursorResult)
        assert result.rowcount == 0, (
            "tenant_id mismatch DELETE が 0 rows でない (tenant boundary 破壊)"
        )
        await session.commit()

        # artifact_a は依然存在 (cross-tenant DELETE で削除されていない)
        check = await session.execute(
            text("select count(*) from artifacts where id = :id"),
            {"id": ARTIFACT_A_ID},
        )
        assert check.scalar() == 1, (
            "tenant boundary 違反で artifact_a が削除された"
        )
