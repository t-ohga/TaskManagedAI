from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
from collections.abc import AsyncIterator
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
from backend.app.repositories.context_snapshot import ContextSnapshotRepository
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

ACTOR_ID = UUID("00000000-0000-4000-8000-000000035001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000035002")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000035003")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000035004")
RUN_A_ID = UUID("00000000-0000-4000-8000-000000035005")
RESEARCH_TASK_A_ID = UUID("00000000-0000-4000-8000-000000035006")
RESEARCH_TASK_B_ID = UUID("00000000-0000-4000-8000-000000035007")
EMPTY_RESEARCH_TASK_A_ID = UUID("00000000-0000-4000-8000-000000035008")
CLAIM_A_ID = UUID("00000000-0000-4000-8000-000000035009")
CLAIM_B_ID = UUID("00000000-0000-4000-8000-000000035010")
SOURCE_ID = UUID("00000000-0000-4000-8000-000000035011")
EVIDENCE_ITEM_A_ID = UUID("00000000-0000-4000-8000-000000035012")
VALID_HASH = "c" * 64
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _valid_prov() -> dict[str, object]:
    return {
        "activities": [{"id": "activity:research", "type": "prov:Activity"}],
        "entities": [{"id": "entity:claim", "type": "prov:Entity"}],
        "wasGeneratedBy": [{"entity": "entity:claim", "activity": "activity:research"}],
    }


def _snapshot_payload() -> dict[str, object]:
    return {
        "prompt_pack_version": "prompt-pack-v1",
        "prompt_pack_lock": "a" * 64,
        "policy_version": "policy-v1",
        "policy_pack_lock": "b" * 64,
        "repo_state": {
            "commit_sha": "1" * 40,
            "branch": "main",
            "dirty": False,
            "diff_hash": "d" * 64,
        },
        "tool_manifest": {
            "registry_version": "tool-registry-v1",
            "allowlist_hash": "e" * 64,
        },
        "provider_continuation_ref": None,
        "provider_request_fingerprint": {"model_resolved": "mock-model"},
        "snapshot_kind": "input",
    }


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-context-snapshot-evidence-hash",
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
            raise AssertionError("ContextSnapshot evidence hash tests require PostgreSQL.") from exc
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
            truncate context_snapshots, evidence_items, claims, evidence_sources,
              research_tasks, agent_runs, projects, workspaces, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_fixtures(session: AsyncSession) -> None:
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
            values (:actor_id, 1, 'human', 'human:snapshot', 'Snapshot Actor',
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'snapshot-workspace', 'snapshot-workspace',
              :actor_id, '{"rls_ready": true}'::jsonb)
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
            insert into agent_runs (id, tenant_id, project_id, status)
            values (:run_a_id, 1, :project_a_id, 'queued')
            """
        ),
        {"run_a_id": RUN_A_ID, "project_a_id": PROJECT_A_ID},
    )
    await session.execute(
        text(
            """
            insert into research_tasks (
              id, tenant_id, project_id, created_by_actor_id, title, status, metadata
            )
            values
              (:task_a_id, 1, :project_a_id, :actor_id, 'Research A', 'queued',
                '{"rls_ready": true}'::jsonb),
              (:empty_task_id, 1, :project_a_id, :actor_id, 'Research Empty', 'queued',
                '{"rls_ready": true}'::jsonb),
              (:task_b_id, 1, :project_b_id, :actor_id, 'Research B', 'queued',
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "task_a_id": RESEARCH_TASK_A_ID,
            "empty_task_id": EMPTY_RESEARCH_TASK_A_ID,
            "task_b_id": RESEARCH_TASK_B_ID,
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "actor_id": ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into evidence_sources (
              id, tenant_id, canonical_url, content_hash, retrieved_at, metadata
            )
            values (
              :source_id, 1, 'https://example.com/source', :content_hash,
              timestamptz '2026-05-16 00:00:00+00', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"source_id": SOURCE_ID, "content_hash": VALID_HASH},
    )
    await session.execute(
        text(
            """
            insert into claims (
              id, tenant_id, project_id, research_task_id, claim_text, provenance_json, metadata
            )
            values
              (:claim_a_id, 1, :project_a_id, :task_a_id, 'Claim A',
                cast(:prov as jsonb), '{"rls_ready": true}'::jsonb),
              (:claim_b_id, 1, :project_b_id, :task_b_id, 'Claim B',
                cast(:prov as jsonb), '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "claim_a_id": CLAIM_A_ID,
            "claim_b_id": CLAIM_B_ID,
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "task_a_id": RESEARCH_TASK_A_ID,
            "task_b_id": RESEARCH_TASK_B_ID,
            "prov": json.dumps(_valid_prov()),
        },
    )
    await session.execute(
        text(
            """
            insert into evidence_items (
              id, tenant_id, project_id, claim_id, source_id, locator, relation, metadata
            )
            values (
              :item_id, 1, :project_a_id, :claim_a_id, :source_id, 'p.1', 'supports',
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "item_id": EVIDENCE_ITEM_A_ID,
            "project_a_id": PROJECT_A_ID,
            "claim_a_id": CLAIM_A_ID,
            "source_id": SOURCE_ID,
        },
    )


def _reference(
    *,
    project_id: UUID = PROJECT_A_ID,
    research_task_id: UUID = RESEARCH_TASK_A_ID,
    claim_ids: tuple[UUID, ...] = (),
    evidence_item_ids: tuple[UUID, ...] = (),
) -> ResearchSetReference:
    return ResearchSetReference(
        project_id=project_id,
        research_task_id=research_task_id,
        claim_ids=claim_ids,
        evidence_item_ids=evidence_item_ids,
    )


def test_context_snapshot_repository_signature_has_no_caller_supplied_hash() -> None:
    signature = inspect.signature(ContextSnapshotRepository.create_snapshot)

    assert "evidence_set_hash" not in signature.parameters
    assert "evidence_set_reference" in signature.parameters


@pytest.mark.asyncio
async def test_caller_supplied_evidence_set_hash_keyword_is_rejected() -> None:
    repo = ContextSnapshotRepository(object())  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        await repo.create_snapshot(
            tenant_id=1,
            run_id=RUN_A_ID,
            evidence_set_hash="f" * 64,  # type: ignore[call-arg]
            **_snapshot_payload(),
        )


@pytest.mark.asyncio
async def test_create_snapshot_computes_evidence_set_hash_server_side(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_fixtures(session)
        repo = ContextSnapshotRepository(session)
        reference = _reference()
        expected_hash = await compute_evidence_set_hash(session, 1, reference)

        snapshot = await repo.create_snapshot(
            tenant_id=1,
            run_id=RUN_A_ID,
            evidence_set_reference=reference,
            **_snapshot_payload(),
        )
        await session.commit()

        stored_hash = await session.scalar(
            text(
                """
                select evidence_set_hash
                from context_snapshots
                where tenant_id = 1 and id = :snapshot_id
                """
            ),
            {"snapshot_id": snapshot.id},
        )

    assert snapshot.evidence_set_hash == expected_hash
    assert stored_hash == expected_hash
    assert _SHA256_RE.fullmatch(snapshot.evidence_set_hash)


@pytest.mark.asyncio
async def test_context_snapshot_rejects_cross_project_research_task_reference(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_fixtures(session)
        repo = ContextSnapshotRepository(session)

        with pytest.raises(ValueError, match="project_id"):
            await repo.create_snapshot(
                tenant_id=1,
                run_id=RUN_A_ID,
                evidence_set_reference=_reference(
                    project_id=PROJECT_B_ID,
                    research_task_id=RESEARCH_TASK_B_ID,
                ),
                **_snapshot_payload(),
            )


@pytest.mark.asyncio
async def test_context_snapshot_rejects_cross_project_claim_reference(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_fixtures(session)
        repo = ContextSnapshotRepository(session)

        with pytest.raises(ValueError, match="claim_ids"):
            await repo.create_snapshot(
                tenant_id=1,
                run_id=RUN_A_ID,
                evidence_set_reference=_reference(claim_ids=(CLAIM_B_ID,)),
                **_snapshot_payload(),
            )


@pytest.mark.asyncio
async def test_none_evidence_set_reference_uses_valid_empty_hash(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_fixtures(session)
        repo = ContextSnapshotRepository(session)

        snapshot = await repo.create_snapshot(
            tenant_id=1,
            run_id=RUN_A_ID,
            evidence_set_reference=None,
            **_snapshot_payload(),
        )

    assert snapshot.evidence_set_hash == EMPTY_EVIDENCE_SET_HASH
    assert _SHA256_RE.fullmatch(snapshot.evidence_set_hash)


@pytest.mark.asyncio
async def test_empty_research_set_reference_is_valid_and_deterministic(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_fixtures(session)
        repo = ContextSnapshotRepository(session)
        reference = _reference(research_task_id=EMPTY_RESEARCH_TASK_A_ID)

        first = await repo.create_snapshot(
            tenant_id=1,
            run_id=RUN_A_ID,
            evidence_set_reference=reference,
            **_snapshot_payload(),
        )
        second = await repo.create_snapshot(
            tenant_id=1,
            run_id=RUN_A_ID,
            evidence_set_reference=reference,
            **_snapshot_payload(),
        )

    assert first.evidence_set_hash == second.evidence_set_hash
    assert _SHA256_RE.fullmatch(first.evidence_set_hash)
