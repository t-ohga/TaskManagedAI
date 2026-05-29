"""SP-012-11.1 BL-TCU-013 contract test: /api/v1/me/current_project.

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時のみ実行。
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.api.me import (
    ProjectAutonomySettingsUpdate,
    ProjectProfileUpdate,
    update_project_autonomy_endpoint,
    update_project_profile_endpoint,
)
from backend.app.config import Settings, get_settings
from backend.app.db.models.project import Project
from backend.app.db.session import create_engine
from backend.app.services.policy.autonomy_settings import (
    AutonomyExpectationMismatch,
    ProjectAutonomySettingsService,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)

ACTOR_ID = UUID("00000000-0000-4000-8000-0000000aa001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-0000000aa002")
PROJECT_FIRST_ID = UUID("00000000-0000-4000-8000-0000000aa003")
PROJECT_SECOND_ID = UUID("00000000-0000-4000-8000-0000000aa004")


def _integration_settings() -> Settings:
    database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL)
    redis_url = os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL)
    return Settings(
        database_url=database_url,
        redis_url=redis_url,
        dev_login_cookie_secret="test-cookie-secret-for-me-api",
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
            raise AssertionError("/me API tests require PostgreSQL.") from exc
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


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate audit_events, projects, workspaces, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_two_projects(session: AsyncSession) -> None:
    """tenant + actor + workspace + 2 projects fixture."""
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
            values (:actor_id, 1, 'human', 'human:default', 'Default Actor',
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
    # 2 projects: first created earlier (project-first)、second 後に作成 (project-second)
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status,
              metadata, created_at)
            values
              (:p1, 1, :ws, 'project-first', 'Project First', 'active',
                '{"rls_ready": true}'::jsonb, '2026-05-22 00:00:00+00'),
              (:p2, 1, :ws, 'project-second', 'Project Second', 'active',
                '{"rls_ready": true}'::jsonb, '2026-05-22 01:00:00+00')
            """
        ),
        {"p1": PROJECT_FIRST_ID, "p2": PROJECT_SECOND_ID, "ws": WORKSPACE_ID},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_current_project_returns_first_project_in_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """tenant 内 2 projects のうち、created_at order で first project を返す."""
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)

    async with session_factory() as session:
        # 直接 repository query で endpoint logic と同等動作を verify
        stmt = (
            select(Project)
            .where(Project.tenant_id == 1)
            .order_by(Project.created_at, Project.slug)
            .limit(1)
        )
        project = (await session.execute(stmt)).scalar_one_or_none()

        assert project is not None
        # first project (created_at が早い方) が返される
        assert project.id == PROJECT_FIRST_ID
        assert project.slug == "project-first"
        assert project.tenant_id == 1


@pytest.mark.asyncio
async def test_project_autonomy_settings_service_updates_only_autonomy_level(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)

    async with session_factory() as session:
        service = ProjectAutonomySettingsService(session)
        # CAS は service signature で必須。expected=現在値 (L0) で更新する。
        result = await service.update_autonomy_level(
            tenant_id=1,
            project_id=PROJECT_SECOND_ID,
            autonomy_level="L2",
            expected_autonomy_level="L0",
        )
        await session.commit()

        assert result is not None
        assert result.previous_autonomy_level == "L0"
        assert result.changed is True
        assert result.project.id == PROJECT_SECOND_ID
        assert result.project.autonomy_level == "L2"
        assert result.project.policy_profile == "default"

    async with session_factory() as session:
        updated = await session.scalar(
            select(Project).where(Project.id == PROJECT_SECOND_ID, Project.tenant_id == 1)
        )

        assert updated is not None
        assert updated.autonomy_level == "L2"
        assert updated.policy_profile == "default"


@pytest.mark.asyncio
async def test_project_autonomy_settings_service_returns_none_for_missing_project(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)

    async with session_factory() as session:
        service = ProjectAutonomySettingsService(session)
        result = await service.update_autonomy_level(
            tenant_id=1,
            project_id=UUID("00000000-0000-4000-8000-0000000aa099"),
            autonomy_level="L1",
            expected_autonomy_level="L0",
        )

        assert result is None


@pytest.mark.asyncio
async def test_project_autonomy_settings_service_raises_on_cas_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex adversarial R9 (HIGH): CAS は service 境界で強制される。expected が DB current と
    不一致なら ``AutonomyExpectationMismatch`` を raise し、DB を変更しない (no-CAS writer 不在)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)
    # PROJECT_SECOND_ID は L0 で開始

    async with session_factory() as session:
        service = ProjectAutonomySettingsService(session)
        with pytest.raises(AutonomyExpectationMismatch) as exc_info:
            await service.update_autonomy_level(
                tenant_id=1,
                project_id=PROJECT_SECOND_ID,
                autonomy_level="L3",
                expected_autonomy_level="L2",  # 実際の current は L0 → 不一致
            )
        assert exc_info.value.expected == "L2"
        assert exc_info.value.actual == "L0"

    # DB は L0 のまま (re-escalation されていない)
    async with session_factory() as session:
        persisted = await session.scalar(
            select(Project).where(Project.id == PROJECT_SECOND_ID, Project.tenant_id == 1)
        )
        assert persisted is not None
        assert persisted.autonomy_level == "L0"


@pytest.mark.asyncio
async def test_project_autonomy_settings_service_no_op_reports_unchanged(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """expected == current == 新値 (no-op) では changed=False を返す (audit 不要を示す)."""
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)

    async with session_factory() as session:
        service = ProjectAutonomySettingsService(session)
        result = await service.update_autonomy_level(
            tenant_id=1,
            project_id=PROJECT_SECOND_ID,
            autonomy_level="L0",
            expected_autonomy_level="L0",
        )
        await session.commit()
        assert result is not None
        assert result.changed is False
        assert result.previous_autonomy_level == "L0"
        assert result.project.autonomy_level == "L0"


@pytest.mark.asyncio
async def test_concurrent_autonomy_updates_cas_admits_single_winner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex adversarial R7/R8 (HIGH): 同一 baseline からの並行 autonomy 更新は CAS により
    1 件だけ成功し、他は 409 になる。

    両 request が expected=L0 で起動する。row lock (``SELECT ... FOR UPDATE``) が直列化し、
    先行 request が L0 -> X を適用して commit する。後続 request は lock 解放後に current=X を
    読み、expected=L0 と不一致のため 409。これにより並行更新でも実遷移は 1 回に確定し、
    permission transition と audit が乖離しない。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)
    # PROJECT_SECOND_ID は server_default の L0 で開始

    async def _update_from_l0(level: str) -> str:
        async with session_factory() as session:
            try:
                await update_project_autonomy_endpoint(
                    project_id=PROJECT_SECOND_ID,
                    payload=ProjectAutonomySettingsUpdate(
                        autonomy_level=level, expected_autonomy_level="L0"
                    ),
                    _cli_capability=None,
                    actor_id=ACTOR_ID,
                    tenant_id=1,
                    session=session,
                )
                return "ok"
            except HTTPException as exc:
                assert exc.status_code == 409
                return "conflict"

    results = await asyncio.gather(_update_from_l0("L1"), _update_from_l0("L2"))

    # ちょうど 1 件が成功し、もう 1 件は CAS 不一致で 409
    assert sorted(results) == ["conflict", "ok"]

    # 実遷移は 1 回のみ → audit は 1 件、previous は必ず L0
    async with session_factory() as session:
        audit_rows = (
            await session.execute(
                text(
                    """
                    select event_payload->>'previous_autonomy_level' as previous,
                           event_payload->>'new_autonomy_level' as new_level
                      from audit_events
                     where event_type = 'config_changed'
                       and event_payload->>'project_id' = :project_id
                    """
                ),
                {"project_id": str(PROJECT_SECOND_ID)},
            )
        ).all()
    assert len(audit_rows) == 1
    assert audit_rows[0].previous == "L0"
    winner_level = audit_rows[0].new_level
    assert winner_level in {"L1", "L2"}

    # DB は winner の値で確定する
    async with session_factory() as session:
        final_project = await session.scalar(
            select(Project).where(Project.id == PROJECT_SECOND_ID, Project.tenant_id == 1)
        )
        assert final_project is not None
        assert final_project.autonomy_level == winner_level
        assert final_project.policy_profile == "default"


@pytest.mark.asyncio
async def test_sequential_autonomy_updates_chain_and_no_op_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex adversarial R2/R7 (HIGH): 正しい baseline での逐次更新は CAS を通り、実遷移ごとに
    1 件 audit を残す。同一値の再送信 (no-op) は CAS を通っても audit を残さない。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)

    async def _update(level: str, expected: str) -> None:
        async with session_factory() as session:
            await update_project_autonomy_endpoint(
                project_id=PROJECT_SECOND_ID,
                payload=ProjectAutonomySettingsUpdate(
                    autonomy_level=level, expected_autonomy_level=expected
                ),
                _cli_capability=None,
                actor_id=ACTOR_ID,
                tenant_id=1,
                session=session,
            )

    await _update("L1", "L0")  # 実遷移 L0 -> L1
    await _update("L2", "L1")  # 実遷移 L1 -> L2
    await _update("L2", "L2")  # no-op (実遷移なし) → audit 残さない

    async with session_factory() as session:
        audit_rows = (
            await session.execute(
                text(
                    """
                    select event_payload->>'previous_autonomy_level' as previous,
                           event_payload->>'new_autonomy_level' as new_level
                      from audit_events
                     where event_type = 'config_changed'
                       and event_payload->>'project_id' = :project_id
                     order by created_at
                    """
                ),
                {"project_id": str(PROJECT_SECOND_ID)},
            )
        ).all()

    # 実遷移は 2 回のみ (no-op は audit を残さない)、一貫した chain を成す
    chain = [(row.previous, row.new_level) for row in audit_rows]
    assert chain == [("L0", "L1"), ("L1", "L2")]

    async with session_factory() as session:
        final_project = await session.scalar(
            select(Project).where(Project.id == PROJECT_SECOND_ID, Project.tenant_id == 1)
        )
        assert final_project is not None
        assert final_project.autonomy_level == "L2"


@pytest.mark.asyncio
async def test_autonomy_compare_and_swap_rejects_stale_expected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex adversarial R7 (HIGH): stale な expected_autonomy_level は 409 で拒否される.

    T1 が L0 -> L1 に更新した後、L0 を基にした stale な更新 (L0 -> L3) は、row lock 後の
    DB current が L1 (= expected L0 と不一致) のため 409 になり、AI 権限の re-escalation を防ぐ。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)
    # PROJECT_SECOND_ID は L0 で開始

    # T1: L0 -> L1 (expected=L0 で正しく適用)
    async with session_factory() as session:
        await update_project_autonomy_endpoint(
            project_id=PROJECT_SECOND_ID,
            payload=ProjectAutonomySettingsUpdate(autonomy_level="L1", expected_autonomy_level="L0"),
            _cli_capability=None,
            actor_id=ACTOR_ID,
            tenant_id=1,
            session=session,
        )

    # T2: stale な baseline L0 から L3 へ上げようとする → DB current は L1 → 409
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await update_project_autonomy_endpoint(
                project_id=PROJECT_SECOND_ID,
                payload=ProjectAutonomySettingsUpdate(
                    autonomy_level="L3", expected_autonomy_level="L0"
                ),
                _cli_capability=None,
                actor_id=ACTOR_ID,
                tenant_id=1,
                session=session,
            )
        assert exc_info.value.status_code == 409

    # DB は L1 のまま (re-escalation されていない)
    async with session_factory() as session:
        persisted = await session.scalar(
            select(Project).where(Project.id == PROJECT_SECOND_ID, Project.tenant_id == 1)
        )
        assert persisted is not None
        assert persisted.autonomy_level == "L1"

    # audit は T1 の L0 -> L1 の 1 件のみ (拒否された T2 は audit を残さない)
    async with session_factory() as session:
        changed = await _profile_config_changed_fields(session, PROJECT_SECOND_ID)
        assert changed == [["autonomy_level"]]


async def _profile_config_changed_fields(
    session: AsyncSession, project_id: UUID
) -> list[list[str]]:
    """config_changed audit の changed_fields (JSON 配列) を created_at 順に返す."""
    rows = (
        await session.execute(
            text(
                """
                select event_payload->>'changed_fields' as changed_fields
                  from audit_events
                 where event_type = 'config_changed'
                   and event_payload->>'project_id' = :project_id
                 order by created_at
                """
            ),
            {"project_id": str(project_id)},
        )
    ).all()
    return [json.loads(row.changed_fields) for row in rows]


@pytest.mark.asyncio
async def test_update_project_profile_endpoint_updates_name_and_description(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """name + description を更新 → 更新後値を返し、audit changed_fields = 実 delta のみ.

    audit payload に name / description の本文値を残さない (changed_fields のみ)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)
    # PROJECT_SECOND_ID: name='Project Second', description=NULL

    async with session_factory() as session:
        response = await update_project_profile_endpoint(
            project_id=PROJECT_SECOND_ID,
            payload=ProjectProfileUpdate(name="Renamed Second", description="新しい説明"),
            _cli_capability=None,
            actor_id=ACTOR_ID,
            tenant_id=1,
            session=session,
        )
        # response は更新後値を反映する (repo.update RETURNING が fresh)
        assert response.name == "Renamed Second"
        assert response.description == "新しい説明"

    # DB に永続化されている
    async with session_factory() as session:
        persisted = await session.scalar(
            select(Project).where(Project.id == PROJECT_SECOND_ID, Project.tenant_id == 1)
        )
        assert persisted is not None
        assert persisted.name == "Renamed Second"
        assert persisted.description == "新しい説明"

    async with session_factory() as session:
        changed = await _profile_config_changed_fields(session, PROJECT_SECOND_ID)
        assert changed == [["description", "name"]]
        # 本文値は audit に残さない
        rows = (
            await session.execute(
                text(
                    "select event_payload::text as raw from audit_events "
                    "where event_type = 'config_changed' "
                    "and event_payload->>'project_id' = :pid"
                ),
                {"pid": str(PROJECT_SECOND_ID)},
            )
        ).all()
        for row in rows:
            assert "Renamed Second" not in row.raw
            assert "新しい説明" not in row.raw


@pytest.mark.asyncio
async def test_update_project_profile_endpoint_audits_only_actual_delta(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex adversarial R3 (MEDIUM): 送信されたが値が変わらない field は changed_fields に
    含めない。name を現行値のまま送り description だけ変更すると changed_fields=["description"]。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)

    async with session_factory() as session:
        response = await update_project_profile_endpoint(
            project_id=PROJECT_SECOND_ID,
            # フォームが常に name を送る挙動を再現: name は現行値と同じ、description のみ変更
            payload=ProjectProfileUpdate(name="Project Second", description="説明だけ更新"),
            _cli_capability=None,
            actor_id=ACTOR_ID,
            tenant_id=1,
            session=session,
        )
        assert response.name == "Project Second"
        assert response.description == "説明だけ更新"

    async with session_factory() as session:
        changed = await _profile_config_changed_fields(session, PROJECT_SECOND_ID)
        # name は実変更でないため除外、description のみ
        assert changed == [["description"]]


@pytest.mark.asyncio
async def test_update_project_profile_endpoint_no_op_skips_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex adversarial R3 (MEDIUM): 現行値と同一の再送信 (no-op) は config_changed を残さない."""
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)

    async with session_factory() as session:
        response = await update_project_profile_endpoint(
            project_id=PROJECT_SECOND_ID,
            # name=現行値 + description=現行値 (NULL) → 実変更なし
            payload=ProjectProfileUpdate(name="Project Second", description=None),
            _cli_capability=None,
            actor_id=ACTOR_ID,
            tenant_id=1,
            session=session,
        )
        # no-op でも現行 project を返す
        assert response.name == "Project Second"
        assert response.description is None

    async with session_factory() as session:
        changed = await _profile_config_changed_fields(session, PROJECT_SECOND_ID)
        assert changed == []


@pytest.mark.asyncio
async def test_update_project_profile_endpoint_404_for_missing_project(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _insert_two_projects(session)

    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await update_project_profile_endpoint(
                project_id=UUID("00000000-0000-4000-8000-0000000aa099"),
                payload=ProjectProfileUpdate(name="X"),
                _cli_capability=None,
                actor_id=ACTOR_ID,
                tenant_id=1,
                session=session,
            )
        assert exc_info.value.status_code == 404
