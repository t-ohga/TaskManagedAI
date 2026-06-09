"""SP-027 (ADR-00053): source trust の DB-backed invariant / contract test。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container (host では skip)。
trust CHECK (score-requires-level) / set_trust / effective 派生 (manual > domain > none) /
cross-tenant 隔離を実 PostgreSQL で固定する。
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
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.repositories.evidence_source import EvidenceSourceRepository
from backend.app.services.research.source_trust import build_source_trust_list

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000047001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000047002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000047003")
TASK_ID = UUID("00000000-0000-4000-8000-000000047004")
CLAIM_ID = UUID("00000000-0000-4000-8000-000000047005")
SOURCE_MANUAL_ID = UUID("00000000-0000-4000-8000-000000047006")  # manual trust 設定
SOURCE_DOMAIN_ID = UUID("00000000-0000-4000-8000-000000047007")  # domain registry hit
SOURCE_NONE_ID = UUID("00000000-0000-4000-8000-000000047008")  # 未登録 domain
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
PROV = (
    '{"activities":[{"id":"activity:research","type":"prov:Activity"}],'
    '"entities":[{"id":"entity:claim","type":"prov:Entity"}],'
    '"wasGeneratedBy":[{"entity":"entity:claim","activity":"activity:research"}]}'
)

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-source-trust",
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous = os.environ.get("TASKMANAGEDAI_DATABASE_URL")
    os.environ["TASKMANAGEDAI_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(_REPO_ROOT / "alembic.ini")), "head")
    finally:
        if previous is None:
            os.environ.pop("TASKMANAGEDAI_DATABASE_URL", None)
        else:
            os.environ["TASKMANAGEDAI_DATABASE_URL"] = previous
        get_settings.cache_clear()


async def _assert_database_available(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("source trust tests require PostgreSQL.") from exc
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
    async with factory() as session:
        await _reset_tables(session)
        await _insert_fixtures(session)
        await session.commit()
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
    return None


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate domain_trust_registry, conflict_groups, notification_events, audit_events,
              ticket_relations, acceptance_criteria, tickets, evidence_items, claims,
              evidence_sources, research_tasks, projects, workspaces, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_fixtures(session: AsyncSession) -> None:
    await session.execute(
        text("insert into tenants (id, name, metadata) values (1, 't', '{\"rls_ready\": true}'::jsonb)")
    )
    await session.execute(
        text(
            "insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata) "
            "values (:a, 1, 'human', 'human:r', 'R', '{\"rls_ready\": true}'::jsonb)"
        ),
        {"a": ACTOR_ID},
    )
    await session.execute(
        text(
            "insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata) "
            "values (:w, 1, 'ws', 'ws', :a, '{\"rls_ready\": true}'::jsonb)"
        ),
        {"w": WORKSPACE_ID, "a": ACTOR_ID},
    )
    await session.execute(
        text(
            "insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata) "
            "values (:p, 1, :w, 'proj', 'proj', 'active', '{\"rls_ready\": true}'::jsonb)"
        ),
        {"p": PROJECT_ID, "w": WORKSPACE_ID},
    )
    await session.execute(
        text(
            "insert into research_tasks (id, tenant_id, project_id, created_by_actor_id, title, status, metadata) "
            "values (:t, 1, :p, :a, 'R', 'queued', '{\"rls_ready\": true}'::jsonb)"
        ),
        {"t": TASK_ID, "p": PROJECT_ID, "a": ACTOR_ID},
    )
    await session.execute(
        text(
            "insert into claims (id, tenant_id, project_id, research_task_id, claim_text, provenance_json, metadata) "
            "values (:c, 1, :p, :t, 'C', cast(:prov as jsonb), '{\"rls_ready\": true}'::jsonb)"
        ),
        {"c": CLAIM_ID, "p": PROJECT_ID, "t": TASK_ID, "prov": PROV},
    )
    # 3 sources: manual trust 設定 / domain registry hit / 未登録 domain。
    await session.execute(
        text(
            """
            insert into evidence_sources
              (id, tenant_id, canonical_url, content_hash, retrieved_at, trust_level, trust_score, metadata)
            values
              (:s1, 1, 'https://manual.example.com/a', :h1, now(), 'high', 0.95, '{"rls_ready": true}'::jsonb),
              (:s2, 1, 'https://trusted.example.org/b', :h2, now(), null, null, '{"rls_ready": true}'::jsonb),
              (:s3, 1, 'https://unknown.example.net/c', :h3, now(), null, null, '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "s1": SOURCE_MANUAL_ID,
            "s2": SOURCE_DOMAIN_ID,
            "s3": SOURCE_NONE_ID,
            "h1": HASH_A,
            "h2": HASH_B,
            "h3": HASH_C,
        },
    )
    for i, src in enumerate((SOURCE_MANUAL_ID, SOURCE_DOMAIN_ID, SOURCE_NONE_ID)):
        await session.execute(
            text(
                "insert into evidence_items "
                "(id, tenant_id, project_id, claim_id, source_id, locator, relation, metadata) "
                "values (:i, 1, :p, :c, :s, :loc, 'supports', '{\"rls_ready\": true}'::jsonb)"
            ),
            {"i": UUID(int=0x47100 + i), "p": PROJECT_ID, "c": CLAIM_ID, "s": src, "loc": f"p.{i}"},
        )
    # domain_trust_registry: trusted.example.org のみ登録 (domain hit のテスト)。
    await session.execute(
        text(
            "insert into domain_trust_registry (id, tenant_id, domain, trust_tier, created_by_actor_id, metadata) "
            "values (:i, 1, 'trusted.example.org', 'medium', :a, '{\"rls_ready\": true}'::jsonb)"
        ),
        {"i": UUID(int=0x47200), "a": ACTOR_ID},
    )


@pytest.mark.asyncio
async def test_trust_score_without_level_rejected_by_check(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text("update evidence_sources set trust_level = null, trust_score = 0.5 where id = :s"),
                {"s": SOURCE_NONE_ID},
            )
            await session.flush()
        assert _sqlstate(exc_info.value) == "23514"
        await session.rollback()


@pytest.mark.asyncio
async def test_set_trust_and_clear(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        repo = EvidenceSourceRepository(session)
        updated = await repo.set_trust(
            tenant_id=1, evidence_source_id=SOURCE_NONE_ID, trust_level="low", trust_score=0.2
        )
        assert updated is not None
        assert updated.trust_level == "low"
        assert updated.trust_score == 0.2
        cleared = await repo.set_trust(
            tenant_id=1, evidence_source_id=SOURCE_NONE_ID, trust_level=None, trust_score=None
        )
        assert cleared is not None
        assert cleared.trust_level is None
        await session.rollback()


@pytest.mark.asyncio
async def test_cross_tenant_set_trust_no_match(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        # tenant 2 から tenant 1 の source を更新試行 → 0 rows (None)。
        await session.execute(
            text("insert into tenants (id, name, metadata) values (2, 't2', '{\"rls_ready\": true}'::jsonb)")
        )
        await session.commit()
        result = await EvidenceSourceRepository(session).set_trust(
            tenant_id=2, evidence_source_id=SOURCE_MANUAL_ID, trust_level="high", trust_score=None
        )
        assert result is None
        await session.rollback()


@pytest.mark.asyncio
async def test_effective_trust_derivation(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        items = await build_source_trust_list(
            session, tenant_id=1, project_id=PROJECT_ID, research_task_id=TASK_ID
        )
    by_id = {i.evidence_source_id: i for i in items}
    # manual override
    assert by_id[SOURCE_MANUAL_ID].origin == "manual"
    assert by_id[SOURCE_MANUAL_ID].trust_level == "high"
    assert by_id[SOURCE_MANUAL_ID].trust_score == 0.95
    # domain registry hit (trusted.example.org -> medium、score null)
    assert by_id[SOURCE_DOMAIN_ID].origin == "domain"
    assert by_id[SOURCE_DOMAIN_ID].trust_level == "medium"
    assert by_id[SOURCE_DOMAIN_ID].trust_score is None
    assert by_id[SOURCE_DOMAIN_ID].match_type == "exact"
    # 未登録 domain
    assert by_id[SOURCE_NONE_ID].origin == "none"
    assert by_id[SOURCE_NONE_ID].trust_level is None


@pytest.mark.asyncio
async def test_domain_registry_does_not_leak_across_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """別 tenant の domain_trust は派生に使わない (registry lookup は tenant scoped)。"""
    async with session_factory() as session:
        await session.execute(
            text("insert into tenants (id, name, metadata) values (2, 't2', '{\"rls_ready\": true}'::jsonb)")
        )
        await session.execute(
            text("insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata) "
                 "values (:a, 2, 'human', 'human:t2', 'T2', '{\"rls_ready\": true}'::jsonb)"),
            {"a": UUID(int=0x47300)},
        )
        # tenant 2 に unknown.example.net を high で登録 (tenant 1 の派生には影響しないはず)。
        await session.execute(
            text("insert into domain_trust_registry (id, tenant_id, domain, trust_tier, created_by_actor_id, metadata) "
                 "values (:i, 2, 'unknown.example.net', 'high', :a, '{\"rls_ready\": true}'::jsonb)"),
            {"i": UUID(int=0x47301), "a": UUID(int=0x47300)},
        )
        await session.commit()
        items = await build_source_trust_list(
            session, tenant_id=1, project_id=PROJECT_ID, research_task_id=TASK_ID
        )
    by_id = {i.evidence_source_id: i for i in items}
    # tenant 1 の unknown.example.net は依然 none (tenant 2 の registry を引かない)。
    assert by_id[SOURCE_NONE_ID].origin == "none"
