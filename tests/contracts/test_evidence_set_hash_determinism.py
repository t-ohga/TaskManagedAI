from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.schemas.research.evidence_set import ResearchSetReference
from backend.app.services.research.evidence_set_hash import (
    EMPTY_EVIDENCE_SET_HASH,
    compute_evidence_set_hash,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000034001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000034002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000034003")
RESEARCH_TASK_ID = UUID("00000000-0000-4000-8000-000000034004")
EMPTY_RESEARCH_TASK_ID = UUID("00000000-0000-4000-8000-000000034005")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _uuid(offset: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{offset:012x}")


def _valid_prov(index: int = 0, *, label: str = "claim") -> dict[str, object]:
    suffix = f"{label}:{index}"
    return {
        "activities": [{"id": f"activity:{suffix}", "type": "prov:Activity"}],
        "entities": [{"id": f"entity:{suffix}", "type": "prov:Entity"}],
        "wasGeneratedBy": [
            {"entity": f"entity:{suffix}", "activity": f"activity:{suffix}"},
        ],
    }


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-evidence-set-hash",
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
            raise AssertionError("Evidence set hash tests require PostgreSQL.") from exc
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
            truncate evidence_items, claims, evidence_sources, research_tasks,
              projects, workspaces, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_base_fixture(session: AsyncSession) -> None:
    await _reset_tables(session)
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
            values (:actor_id, 1, 'human', 'human:evidence-hash', 'Evidence Hash Actor',
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'evidence-hash', 'evidence-hash', :actor_id,
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'project-a', 'project-a', 'active',
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
    )
    await session.execute(
        text(
            """
            insert into research_tasks (
              id, tenant_id, project_id, created_by_actor_id, title, status, metadata
            )
            values
              (:task_id, 1, :project_id, :actor_id, 'Research A', 'queued',
                '{"rls_ready": true}'::jsonb),
              (:empty_task_id, 1, :project_id, :actor_id, 'Research Empty', 'queued',
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "task_id": RESEARCH_TASK_ID,
            "empty_task_id": EMPTY_RESEARCH_TASK_ID,
            "project_id": PROJECT_ID,
            "actor_id": ACTOR_ID,
        },
    )


async def _insert_claims_with_evidence(
    session: AsyncSession,
    count: int,
    *,
    claim_text: Callable[[int], str] | None = None,
    source_url: Callable[[int], str] | None = None,
    provenance_json: Callable[[int], dict[str, object]] | None = None,
) -> tuple[list[UUID], list[UUID], list[UUID]]:
    claim_text = claim_text or (lambda i: f"Claim {i}")
    source_url = source_url or (lambda i: f"https://example.com/source/{i}")
    provenance_json = provenance_json or _valid_prov

    source_rows = []
    claim_rows = []
    item_rows = []
    claim_ids: list[UUID] = []
    source_ids: list[UUID] = []
    item_ids: list[UUID] = []

    for index in range(count):
        claim_id = _uuid(0x341000 + index)
        source_id = _uuid(0x342000 + index)
        item_id = _uuid(0x343000 + index)
        claim_ids.append(claim_id)
        source_ids.append(source_id)
        item_ids.append(item_id)
        source_rows.append(
            {
                "source_id": source_id,
                "url": source_url(index),
                "content_hash": hashlib_for_fixture(f"source:{index}"),
            }
        )
        claim_rows.append(
            {
                "claim_id": claim_id,
                "project_id": PROJECT_ID,
                "task_id": RESEARCH_TASK_ID,
                "claim_text": claim_text(index),
                "prov": json.dumps(provenance_json(index), ensure_ascii=False),
            }
        )
        item_rows.append(
            {
                "item_id": item_id,
                "project_id": PROJECT_ID,
                "claim_id": claim_id,
                "source_id": source_id,
                "locator": f"p.{index}",
                "relation": "supports",
            }
        )

    await session.execute(
        text(
            """
            insert into evidence_sources (
              id, tenant_id, canonical_url, content_hash, retrieved_at, metadata
            )
            values (
              :source_id, 1, :url, :content_hash,
              timestamptz '2026-05-16 00:00:00+00', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        source_rows,
    )
    await session.execute(
        text(
            """
            insert into claims (
              id, tenant_id, project_id, research_task_id, claim_text, provenance_json, metadata
            )
            values (
              :claim_id, 1, :project_id, :task_id, :claim_text,
              cast(:prov as jsonb), '{"rls_ready": true}'::jsonb
            )
            """
        ),
        claim_rows,
    )
    await session.execute(
        text(
            """
            insert into evidence_items (
              id, tenant_id, project_id, claim_id, source_id, locator, relation, metadata
            )
            values (
              :item_id, 1, :project_id, :claim_id, :source_id, :locator, :relation,
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        item_rows,
    )
    return claim_ids, source_ids, item_ids


def hashlib_for_fixture(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _reference(
    *,
    claim_ids: list[UUID] | None = None,
    evidence_item_ids: list[UUID] | None = None,
    research_task_id: UUID = RESEARCH_TASK_ID,
) -> ResearchSetReference:
    return ResearchSetReference(
        project_id=PROJECT_ID,
        research_task_id=research_task_id,
        claim_ids=tuple(claim_ids or ()),
        evidence_item_ids=tuple(evidence_item_ids or ()),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("claim_count", [1, 10, 100, 1000])
async def test_evidence_set_hash_is_deterministic_for_claim_counts(
    session_factory: async_sessionmaker[AsyncSession],
    claim_count: int,
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)
        await _insert_claims_with_evidence(session, claim_count)

        started = time.perf_counter()
        first = await compute_evidence_set_hash(session, 1, _reference())
        second = await compute_evidence_set_hash(session, 1, _reference())
        elapsed = time.perf_counter() - started

    assert first == second
    assert _SHA256_RE.fullmatch(first)
    if claim_count == 1000:
        assert elapsed < 5.0


@pytest.mark.asyncio
async def test_evidence_set_hash_1000_plus_fixture_variants_are_reproducible(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)
        await _insert_claims_with_evidence(
            session,
            1001,
            claim_text=lambda i: "Cafe\u0301" if i % 2 else "Café",
            source_url=lambda i: (
                f"HTTP://Example.COM:80/source/{i}/"
                if i % 2
                else f"http://example.com/source/{i}"
            ),
            provenance_json=lambda i: _valid_prov(i, label="cafe\u0301" if i % 2 else "café"),
        )

        first = await compute_evidence_set_hash(session, 1, _reference())
        second = await compute_evidence_set_hash(session, 1, _reference())

    assert first == second
    assert _SHA256_RE.fullmatch(first)


@pytest.mark.asyncio
async def test_nfc_normalization_makes_nfd_and_nfc_claim_content_equivalent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)
        claim_ids, _, _ = await _insert_claims_with_evidence(
            session,
            1,
            claim_text=lambda _: "Cafe\u0301",
            provenance_json=lambda _: _valid_prov(0, label="cafe\u0301"),
        )

        first = await compute_evidence_set_hash(session, 1, _reference())
        await session.execute(
            text(
                """
                update claims
                set claim_text = :claim_text,
                    provenance_json = cast(:prov as jsonb)
                where tenant_id = 1 and id = :claim_id
                """
            ),
            {
                "claim_text": "Café",
                "prov": json.dumps(_valid_prov(0, label="café"), ensure_ascii=False),
                "claim_id": claim_ids[0],
            },
        )
        second = await compute_evidence_set_hash(session, 1, _reference())

    assert first == second


@pytest.mark.asyncio
async def test_url_normalization_lowercases_host_strips_default_port_and_trailing_slash(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)
        _, source_ids, _ = await _insert_claims_with_evidence(
            session,
            1,
            source_url=lambda _: "HTTP://Example.COM:80/foo/",
        )

        first = await compute_evidence_set_hash(session, 1, _reference())
        await session.execute(
            text(
                """
                update evidence_sources
                set canonical_url = 'http://example.com/foo'
                where tenant_id = 1 and id = :source_id
                """
            ),
            {"source_id": source_ids[0]},
        )
        second = await compute_evidence_set_hash(session, 1, _reference())

    assert first == second


@pytest.mark.asyncio
async def test_claim_and_source_sorting_make_reference_order_irrelevant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)
        claim_ids, _, item_ids = await _insert_claims_with_evidence(session, 3)

        forward = await compute_evidence_set_hash(
            session,
            1,
            _reference(claim_ids=claim_ids, evidence_item_ids=item_ids),
        )
        reversed_order = await compute_evidence_set_hash(
            session,
            1,
            _reference(
                claim_ids=list(reversed(claim_ids)),
                evidence_item_ids=list(reversed(item_ids)),
            ),
        )

    assert forward == reversed_order


@pytest.mark.asyncio
async def test_prov_bundle_hash_is_independent_of_json_key_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)
        claim_ids, _, _ = await _insert_claims_with_evidence(session, 1)

        first = await compute_evidence_set_hash(session, 1, _reference())
        reordered = {
            "wasGeneratedBy": [
                {"activity": "activity:claim:0", "entity": "entity:claim:0"},
            ],
            "entities": [{"type": "prov:Entity", "id": "entity:claim:0"}],
            "activities": [{"type": "prov:Activity", "id": "activity:claim:0"}],
        }
        await session.execute(
            text(
                """
                update claims
                set provenance_json = cast(:prov as jsonb)
                where tenant_id = 1 and id = :claim_id
                """
            ),
            {"prov": json.dumps(reordered), "claim_id": claim_ids[0]},
        )
        second = await compute_evidence_set_hash(session, 1, _reference())

    assert first == second


@pytest.mark.asyncio
async def test_empty_set_hash_is_deterministic_and_valid(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_base_fixture(session)

        none_hash = await compute_evidence_set_hash(session, 1, None)
        empty_task_first = await compute_evidence_set_hash(
            session,
            1,
            _reference(research_task_id=EMPTY_RESEARCH_TASK_ID),
        )
        empty_task_second = await compute_evidence_set_hash(
            session,
            1,
            _reference(research_task_id=EMPTY_RESEARCH_TASK_ID),
        )

    assert none_hash == EMPTY_EVIDENCE_SET_HASH
    assert empty_task_first == empty_task_second
    assert _SHA256_RE.fullmatch(none_hash)
    assert _SHA256_RE.fullmatch(empty_task_first)
