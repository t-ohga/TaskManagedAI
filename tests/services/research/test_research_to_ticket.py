from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import unicodedata
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.models.ticket import Ticket
from backend.app.db.session import create_engine
from backend.app.schemas.research.evidence_set import ResearchSetReference
from backend.app.schemas.research.research_to_ticket import ResearchToTicketRequest
from backend.app.services.research.evidence_set_hash import compute_evidence_set_hash
from backend.app.services.research.research_to_ticket import ResearchToTicketAdapter

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[3]

ACTOR_ID = UUID("00000000-0000-4000-8000-000000036001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000036002")
PROJECT_A_ID = UUID("00000000-0000-4000-8000-000000036003")
PROJECT_B_ID = UUID("00000000-0000-4000-8000-000000036004")
RESEARCH_TASK_A_ID = UUID("00000000-0000-4000-8000-000000036005")
RESEARCH_TASK_B_ID = UUID("00000000-0000-4000-8000-000000036006")
EMPTY_RESEARCH_TASK_ID = UUID("00000000-0000-4000-8000-000000036007")
CLAIM_A_ID = UUID("00000000-0000-4000-8000-000000036008")
SOURCE_ID = UUID("00000000-0000-4000-8000-000000036009")
EVIDENCE_ITEM_A_ID = UUID("00000000-0000-4000-8000-000000036010")
VALID_HASH = "d" * 64
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PREFIX16_RE = re.compile(r"^[0-9a-f]{16}$")


def _valid_prov(*, raw_secret: str | None = None) -> dict[str, object]:
    entity: dict[str, object] = {"id": "entity:claim", "type": "prov:Entity"}
    if raw_secret is not None:
        entity["raw_note"] = raw_secret
    return {
        "activities": [{"id": "activity:research", "type": "prov:Activity"}],
        "entities": [entity],
        "wasGeneratedBy": [{"entity": "entity:claim", "activity": "activity:research"}],
    }


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-research-to-ticket",
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
            raise AssertionError("Research-to-Ticket tests require PostgreSQL.") from exc
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
            truncate notification_events, audit_events, ticket_relations,
              acceptance_criteria, tickets, evidence_items, claims, evidence_sources,
              research_tasks, repositories, projects, workspaces, principals, actors, tenants
            restart identity cascade
            """
        )
    )


async def _insert_fixtures(
    session: AsyncSession,
    *,
    include_claim: bool = True,
    include_evidence: bool = True,
    raw_secret_in_prov: bool = False,
    task_title: str = "Research A",
) -> None:
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
            values (:actor_id, 1, 'human', 'human:research-ticket', 'Research Ticket Actor',
              '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'research-ticket', 'research-ticket', :actor_id,
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
            insert into research_tasks (
              id, tenant_id, project_id, created_by_actor_id, title, status, metadata
            )
            values
              (:task_a_id, 1, :project_a_id, :actor_id, :task_title, 'completed',
                '{"rls_ready": true}'::jsonb),
              (:empty_task_id, 1, :project_a_id, :actor_id, 'Research Empty', 'completed',
                '{"rls_ready": true}'::jsonb),
              (:task_b_id, 1, :project_b_id, :actor_id, 'Research B', 'completed',
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "task_a_id": RESEARCH_TASK_A_ID,
            "task_b_id": RESEARCH_TASK_B_ID,
            "empty_task_id": EMPTY_RESEARCH_TASK_ID,
            "project_a_id": PROJECT_A_ID,
            "project_b_id": PROJECT_B_ID,
            "actor_id": ACTOR_ID,
            "task_title": task_title,
        },
    )
    if not include_claim:
        return

    raw_secret = "sk-" + ("A" * 40) if raw_secret_in_prov else None
    await session.execute(
        text(
            """
            insert into claims (
              id, tenant_id, project_id, research_task_id, claim_text, provenance_json, metadata
            )
            values (
              :claim_id, 1, :project_id, :task_id, 'Claim A',
              cast(:prov as jsonb), '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "claim_id": CLAIM_A_ID,
            "project_id": PROJECT_A_ID,
            "task_id": RESEARCH_TASK_A_ID,
            "prov": json.dumps(_valid_prov(raw_secret=raw_secret)),
        },
    )
    if not include_evidence:
        return

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
            insert into evidence_items (
              id, tenant_id, project_id, claim_id, source_id, locator, relation, metadata
            )
            values (
              :item_id, 1, :project_id, :claim_id, :source_id, 'p.1', 'supports',
              '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {
            "item_id": EVIDENCE_ITEM_A_ID,
            "project_id": PROJECT_A_ID,
            "claim_id": CLAIM_A_ID,
            "source_id": SOURCE_ID,
        },
    )


def _request(
    *,
    project_id: UUID = PROJECT_A_ID,
    research_task_id: UUID = RESEARCH_TASK_A_ID,
    ticket_title_override: str | None = None,
) -> ResearchToTicketRequest:
    return ResearchToTicketRequest(
        tenant_id=1,
        project_id=project_id,
        research_task_id=research_task_id,
        requested_by_actor_id=ACTOR_ID,
        ticket_title_override=ticket_title_override,
    )


async def _promote_once(session_factory: async_sessionmaker[AsyncSession]) -> str:
    async with session_factory() as session:
        await _insert_fixtures(session)
        outcome = await ResearchToTicketAdapter(session).promote(_request())
    return outcome.artifact_hash


def test_research_to_ticket_request_has_no_caller_supplied_binding_fields() -> None:
    assert "artifact_hash" not in ResearchToTicketRequest.model_fields
    assert "evidence_set_hash" not in ResearchToTicketRequest.model_fields
    assert "ticket_id" not in ResearchToTicketRequest.model_fields

    signature = inspect.signature(ResearchToTicketAdapter.promote)
    assert "artifact_hash" not in signature.parameters
    assert "evidence_set_hash" not in signature.parameters
    assert "ticket_id" not in signature.parameters
    assert tuple(signature.parameters) == ("self", "request")


@pytest.mark.asyncio
async def test_artifact_hash_is_deterministic_and_server_side_computed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_hash = await _promote_once(session_factory)
    second_hash = await _promote_once(session_factory)

    assert first_hash == second_hash
    assert _SHA256_RE.fullmatch(first_hash)

    async with session_factory() as session:
        await _insert_fixtures(session)
        adapter = ResearchToTicketAdapter(session)
        with pytest.raises(TypeError, match="artifact_hash"):
            await adapter.promote(_request(), artifact_hash="f" * 64)  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_ticket_metadata_and_audit_payload_are_server_owned_and_raw_secret_free(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    raw_secret = "sk-" + ("A" * 40)
    async with session_factory() as session:
        await _insert_fixtures(session, raw_secret_in_prov=True)
        outcome = await ResearchToTicketAdapter(session).promote(_request())

        ticket = await session.scalar(select(Ticket).where(Ticket.id == outcome.ticket_id))
        event = await session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "research_to_ticket_promoted")
        )

    assert ticket is not None
    assert ticket.project_id == PROJECT_A_ID
    assert ticket.repository_id is None
    assert ticket.status == "open"
    assert ticket.priority == "medium"
    assert ticket.metadata_["rls_ready"] is True
    assert ticket.metadata_["research_task_id"] == str(RESEARCH_TASK_A_ID)
    assert ticket.metadata_["artifact_hash"] == outcome.artifact_hash
    assert ticket.metadata_["evidence_set_hash"] == outcome.evidence_set_hash
    assert ticket.metadata_["claim_count"] == 1
    assert ticket.metadata_["evidence_item_count"] == 1
    assert "policy_version" in ticket.metadata_
    assert _PREFIX16_RE.fullmatch(ticket.metadata_["provenance_json_hash"])

    assert event is not None
    payload = event.event_payload
    assert {
        "tenant_id",
        "actor_id",
        "research_task_id",
        "ticket_id",
        "claim_id",
        "evidence_set_hash",
        "provenance_json_hash",
        "artifact_hash",
        "policy_version",
        "timestamp",
    }.issubset(payload)
    assert payload["tenant_id"] == 1
    assert payload["actor_id"] == str(ACTOR_ID)
    assert payload["research_task_id"] == str(RESEARCH_TASK_A_ID)
    assert payload["ticket_id"] == str(outcome.ticket_id)
    assert payload["claim_id"] is None
    assert payload["artifact_hash"] == outcome.artifact_hash
    assert payload["evidence_set_hash"] == outcome.evidence_set_hash
    assert _PREFIX16_RE.fullmatch(payload["provenance_json_hash"])
    assert "provenance_json" not in payload
    assert raw_secret not in repr(payload)
    assert "sk-" not in repr(payload)


@pytest.mark.asyncio
async def test_cross_project_research_task_reference_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_fixtures(session)
        adapter = ResearchToTicketAdapter(session)

        with pytest.raises(ValueError, match="research_task_id not reachable in tenant/project"):
            await adapter.promote(
                _request(
                    project_id=PROJECT_B_ID,
                    research_task_id=RESEARCH_TASK_A_ID,
                )
            )


@pytest.mark.asyncio
async def test_empty_claim_set_creates_valid_ticket_with_server_evidence_hash(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _insert_fixtures(session, include_claim=False)
        expected_hash = await compute_evidence_set_hash(
            session,
            1,
            ResearchSetReference(
                project_id=PROJECT_A_ID,
                research_task_id=EMPTY_RESEARCH_TASK_ID,
            ),
        )

        outcome = await ResearchToTicketAdapter(session).promote(
            _request(research_task_id=EMPTY_RESEARCH_TASK_ID)
        )
        ticket = await session.scalar(select(Ticket).where(Ticket.id == outcome.ticket_id))

    assert outcome.claim_count == 0
    assert outcome.evidence_item_count == 0
    assert outcome.evidence_set_hash == expected_hash
    assert _SHA256_RE.fullmatch(outcome.evidence_set_hash)
    assert ticket is not None
    assert ticket.metadata_["rls_ready"] is True
    assert ticket.metadata_["claim_count"] == 0
    assert ticket.metadata_["evidence_item_count"] == 0


@pytest.mark.asyncio
async def test_ticket_title_override_is_nfc_normalized_and_truncated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    override = "Cafe\u0301 " + ("x" * 250)

    async with session_factory() as session:
        await _insert_fixtures(session)
        outcome = await ResearchToTicketAdapter(session).promote(
            _request(ticket_title_override=override)
        )
        ticket = await session.scalar(select(Ticket).where(Ticket.id == outcome.ticket_id))

    assert ticket is not None
    assert ticket.title.startswith("Café")
    assert len(ticket.title) == 200
    assert unicodedata.is_normalized("NFC", ticket.title)
