"""SP-032 (ADR-00052): research advanced の DB-backed invariant / contract test。

DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container (host では skip)。
4-col 複合 FK / domain unique / conflict_group RESTRICT delete / resolved-note CHECK /
矛盾検出 / freshness + domain trust enrichment を実 PostgreSQL で固定する。
"""

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
from backend.app.repositories.conflict_group import ConflictGroupRepository
from backend.app.repositories.domain_trust import DomainTrustRepository
from backend.app.services.research.conflict_detection import list_conflict_candidates
from backend.app.services.research.read_redaction import to_domain_trust_read
from backend.app.services.research.research_advanced import build_research_advanced_summary
from backend.app.services.security.secret_text_scan import REDACTED_PLACEHOLDER

_SECRET_SHAPED = "sk-proj-abcdefghijklmnopqrstuvwxyz012345"

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000045001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000045002")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000045003")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000045004")
TASK_A_ID = UUID("00000000-0000-4000-8000-000000045005")
TASK_B_ID = UUID("00000000-0000-4000-8000-000000045006")
CLAIM_A1_ID = UUID("00000000-0000-4000-8000-000000045007")
CLAIM_A2_ID = UUID("00000000-0000-4000-8000-000000045008")
CLAIM_B_ID = UUID("00000000-0000-4000-8000-000000045009")
SOURCE_ID = UUID("00000000-0000-4000-8000-000000045010")
EVIDENCE_SUPPORT_ID = UUID("00000000-0000-4000-8000-000000045011")
EVIDENCE_CONTRADICT_ID = UUID("00000000-0000-4000-8000-000000045012")
VALID_HASH = "c" * 64
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
        dev_login_cookie_secret="test-cookie-secret-research-advanced",
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
            raise AssertionError("research advanced tests require PostgreSQL.") from exc
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


def _constraint_name(error: BaseException) -> str | None:
    return (
        getattr(error, "constraint_name", None)
        or getattr(getattr(error, "orig", None), "constraint_name", None)
        or getattr(getattr(getattr(error, "orig", None), "__cause__", None), "constraint_name", None)
    )


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
        text("insert into tenants (id, name, metadata) values (1, 'tenant-one', '{\"rls_ready\": true}'::jsonb)")
    )
    await session.execute(
        text(
            "insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata) "
            "values (:a, 1, 'human', 'human:research', 'Research', '{\"rls_ready\": true}'::jsonb)"
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
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:pa, 1, :w, 'project-a', 'project-a', 'active', '{"rls_ready": true}'::jsonb),
                   (:pb, 1, :w, 'project-b', 'project-b', 'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"pa": PROJECT_A_ID, "pb": PROJECT_B_ID, "w": WORKSPACE_ID},
    )
    await session.execute(
        text(
            """
            insert into research_tasks (id, tenant_id, project_id, created_by_actor_id, title, status, metadata)
            values (:ta, 1, :pa, :a, 'Research A', 'queued', '{"rls_ready": true}'::jsonb),
                   (:tb, 1, :pb, :a, 'Research B', 'queued', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"ta": TASK_A_ID, "tb": TASK_B_ID, "pa": PROJECT_A_ID, "pb": PROJECT_B_ID, "a": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into claims
              (id, tenant_id, project_id, research_task_id, claim_text, provenance_json, metadata)
            values
              (:c1, 1, :pa, :ta, 'Claim A1', cast(:prov as jsonb), '{"rls_ready": true}'::jsonb),
              (:c2, 1, :pa, :ta, 'Claim A2', cast(:prov as jsonb), '{"rls_ready": true}'::jsonb),
              (:cb, 1, :pb, :tb, 'Claim B', cast(:prov as jsonb), '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "c1": CLAIM_A1_ID,
            "c2": CLAIM_A2_ID,
            "cb": CLAIM_B_ID,
            "pa": PROJECT_A_ID,
            "pb": PROJECT_B_ID,
            "ta": TASK_A_ID,
            "tb": TASK_B_ID,
            "prov": PROV,
        },
    )
    await session.execute(
        text(
            "insert into evidence_sources "
            "(id, tenant_id, canonical_url, content_hash, retrieved_at, published_at, metadata) "
            "values (:s, 1, 'https://www.example.com/source', :h, "
            "timestamptz '2026-01-01 00:00:00+00', timestamptz '2025-06-09 00:00:00+00', "
            "'{\"rls_ready\": true}'::jsonb)"
        ),
        {"s": SOURCE_ID, "h": VALID_HASH},
    )
    # claim A1: supports + contradicts (= conflict candidate)。claim A2: 証拠なし。
    await session.execute(
        text(
            """
            insert into evidence_items
              (id, tenant_id, project_id, claim_id, source_id, locator, relation, metadata)
            values
              (:s1, 1, :pa, :c1, :src, 'p.1', 'supports', '{"rls_ready": true}'::jsonb),
              (:s2, 1, :pa, :c1, :src, 'p.2', 'contradicts', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "s1": EVIDENCE_SUPPORT_ID,
            "s2": EVIDENCE_CONTRADICT_ID,
            "pa": PROJECT_A_ID,
            "c1": CLAIM_A1_ID,
            "src": SOURCE_ID,
        },
    )


async def _make_group(session: AsyncSession, *, project_id: UUID, task_id: UUID, title: str = "G") -> UUID:
    group = await ConflictGroupRepository(session).create_conflict_group(
        tenant_id=1,
        project_id=project_id,
        research_task_id=task_id,
        title=title,
        created_by_actor_id=ACTOR_ID,
    )
    await session.commit()
    return group.id


@pytest.mark.asyncio
async def test_create_group_and_assign_claim(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        group_id = await _make_group(session, project_id=PROJECT_A_ID, task_id=TASK_A_ID)
        repo = ConflictGroupRepository(session)
        claim = await repo.assign_claim(
            tenant_id=1, project_id=PROJECT_A_ID, research_task_id=TASK_A_ID, group_id=group_id, claim_id=CLAIM_A1_ID
        )
        await session.commit()
        assert claim is not None
        assert claim.conflict_group_id == group_id


@pytest.mark.asyncio
async def test_assign_claim_from_other_research_task_no_match(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """task A の group に task B の claim を assign → repo scope で no match (None)。"""
    async with session_factory() as session:
        group_id = await _make_group(session, project_id=PROJECT_A_ID, task_id=TASK_A_ID)
        repo = ConflictGroupRepository(session)
        result = await repo.assign_claim(
            tenant_id=1, project_id=PROJECT_A_ID, research_task_id=TASK_A_ID, group_id=group_id, claim_id=CLAIM_B_ID
        )
        assert result is None
        await session.rollback()


@pytest.mark.asyncio
async def test_raw_cross_task_assignment_rejected_by_fk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """直接 SQL で task B の claim に task A の group を束ねる → 4-col FK violation。"""
    async with session_factory() as session:
        group_id = await _make_group(session, project_id=PROJECT_A_ID, task_id=TASK_A_ID)
        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text("update claims set conflict_group_id = :g where id = :c"),
                {"g": group_id, "c": CLAIM_B_ID},
            )
            await session.flush()
        assert _sqlstate(exc_info.value) == "23503"
        assert _constraint_name(exc_info.value) == "claims_conflict_group_fkey"
        await session.rollback()


@pytest.mark.asyncio
async def test_conflict_group_delete_restricted_while_referenced(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        group_id = await _make_group(session, project_id=PROJECT_A_ID, task_id=TASK_A_ID)
        await ConflictGroupRepository(session).assign_claim(
            tenant_id=1, project_id=PROJECT_A_ID, research_task_id=TASK_A_ID, group_id=group_id, claim_id=CLAIM_A1_ID
        )
        await session.commit()
        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(text("delete from conflict_groups where id = :g"), {"g": group_id})
            await session.flush()
        assert _sqlstate(exc_info.value) == "23503"
        await session.rollback()


@pytest.mark.asyncio
async def test_resolved_requires_note_check(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        group_id = await _make_group(session, project_id=PROJECT_A_ID, task_id=TASK_A_ID)
        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text("update conflict_groups set status = 'resolved' where id = :g"),
                {"g": group_id},
            )
            await session.flush()
        assert _sqlstate(exc_info.value) == "23514"
        assert _constraint_name(exc_info.value) == "conflict_groups_ck_resolved_note_required"
        await session.rollback()


@pytest.mark.asyncio
async def test_domain_trust_duplicate_rejected(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        repo = DomainTrustRepository(session)
        await repo.create_domain_trust(
            tenant_id=1, domain="example.com", trust_tier="high", rationale=None, created_by_actor_id=ACTOR_ID
        )
        await session.commit()
        with pytest.raises(IntegrityError) as exc_info:
            await repo.create_domain_trust(
                tenant_id=1, domain="example.com", trust_tier="low", rationale=None, created_by_actor_id=ACTOR_ID
            )
            await session.flush()
        assert _constraint_name(exc_info.value) == "domain_trust_registry_uq_tenant_domain"
        await session.rollback()


@pytest.mark.asyncio
async def test_conflict_candidates_only_contradicting(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        candidates, coverage = await list_conflict_candidates(
            session, tenant_id=1, project_id=PROJECT_A_ID, research_task_id=TASK_A_ID
        )
        candidate_ids = {c.claim_id for c in candidates}
        # claim A1 (contradicts evidence) のみ candidate、claim A2 (証拠なし) は除外。
        assert candidate_ids == {CLAIM_A1_ID}
        a1 = next(c for c in candidates if c.claim_id == CLAIM_A1_ID)
        assert a1.contradicting_count == 1
        assert a1.supporting_count == 1
        # relation_coverage = evidence を持つ claim (A1) / 全 claim (A1, A2) = 0.5
        assert coverage == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_research_advanced_summary_domain_trust_and_freshness(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        # www.example.com を registry に登録 (hostname exact match)。
        await DomainTrustRepository(session).create_domain_trust(
            tenant_id=1, domain="www.example.com", trust_tier="high", rationale="trusted", created_by_actor_id=ACTOR_ID
        )
        await session.commit()
        as_of = datetime(2025, 6, 9, tzinfo=UTC)  # published_at と同日 → freshness ≈ 1.0
        summary = await build_research_advanced_summary(
            session, tenant_id=1, project_id=PROJECT_A_ID, research_task_id=TASK_A_ID, as_of=as_of
        )

    # conflict candidates
    assert {c.claim_id for c in summary.conflict_candidates} == {CLAIM_A1_ID}
    # claim_freshness: A1 は supporting evidence (published 2025-06-09) → ≈1.0、A2 は null
    fresh_by_claim = {f.claim_id: f for f in summary.claim_freshness}
    assert fresh_by_claim[CLAIM_A1_ID].computed_freshness == pytest.approx(1.0, abs=1e-6)
    assert fresh_by_claim[CLAIM_A2_ID].computed_freshness is None
    # evidence domain trust: www.example.com → exact / high
    trust = summary.evidence_domain_trust
    assert len(trust) == 1
    assert trust[0].domain == "www.example.com"
    assert trust[0].trust_tier == "high"
    assert trust[0].match_type == "exact"


@pytest.mark.asyncio
async def test_summary_domain_trust_none_when_unregistered(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        summary = await build_research_advanced_summary(
            session, tenant_id=1, project_id=PROJECT_A_ID, research_task_id=TASK_A_ID
        )
    assert summary.evidence_domain_trust[0].match_type == "none"
    assert summary.evidence_domain_trust[0].trust_tier is None


@pytest.mark.asyncio
async def test_domain_trust_rationale_secret_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex adversarial R2 F-HIGH: rationale の modern provider key を write 前に reject。"""
    async with session_factory() as session:
        repo = DomainTrustRepository(session)
        with pytest.raises(ValueError, match="forbidden secret pattern|secret"):
            await repo.create_domain_trust(
                tenant_id=1,
                domain="example.com",
                trust_tier="high",
                rationale="key: sk-proj-abcdefghijklmnopqrstuvwxyz012345",
                created_by_actor_id=ACTOR_ID,
            )
        await session.rollback()
    # row が永続化されていないこと
    async with session_factory() as session:
        entries = await DomainTrustRepository(session).list_domain_trust(tenant_id=1)
        assert all(e.domain != "example.com" for e in entries)


@pytest.mark.asyncio
async def test_summary_redacts_direct_written_secret_conflict_group(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex R3 F-CRITICAL: direct-write された secret-shaped title が summary で redaction される。"""
    group_id = UUID("00000000-0000-4000-8000-000000045020")
    async with session_factory() as session:
        await session.execute(
            text(
                """
                insert into conflict_groups
                  (id, tenant_id, project_id, research_task_id, title, status, created_by_actor_id, metadata)
                values (:g, 1, :pa, :ta, :title, 'open', :actor, '{"rls_ready": true}'::jsonb)
                """
            ),
            {"g": group_id, "pa": PROJECT_A_ID, "ta": TASK_A_ID, "title": f"key {_SECRET_SHAPED}", "actor": ACTOR_ID},
        )
        await session.commit()
        summary = await build_research_advanced_summary(
            session, tenant_id=1, project_id=PROJECT_A_ID, research_task_id=TASK_A_ID
        )
    titles = {g.title for g in summary.conflict_groups}
    assert REDACTED_PLACEHOLDER in titles
    assert all(_SECRET_SHAPED not in (g.title or "") for g in summary.conflict_groups)


@pytest.mark.asyncio
async def test_read_redacts_direct_written_secret_domain(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex R3 F-CRITICAL: direct-write された secret-shaped domain が read で redaction される。"""
    entry_id = UUID("00000000-0000-4000-8000-000000045021")
    tainted = f"{_SECRET_SHAPED}.example.com"  # DB CHECK `^[a-z0-9.-]+$` は通る (normalize bypass)
    async with session_factory() as session:
        await session.execute(
            text(
                """
                insert into domain_trust_registry
                  (id, tenant_id, domain, trust_tier, created_by_actor_id, metadata)
                values (:e, 1, :d, 'high', :actor, '{"rls_ready": true}'::jsonb)
                """
            ),
            {"e": entry_id, "d": tainted, "actor": ACTOR_ID},
        )
        await session.commit()
        entry = await DomainTrustRepository(session).get_domain_trust(tenant_id=1, entry_id=entry_id)
    assert entry is not None
    read = to_domain_trust_read(entry)
    assert read.domain == REDACTED_PLACEHOLDER
