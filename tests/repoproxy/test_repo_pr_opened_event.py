"""SP-008 Batch D: RepoProxy repo_pr_opened AgentRunEvent tests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from asyncpg.exceptions import PostgresError  # type: ignore[import-untyped]
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.session import create_engine
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.repoproxy.repo_pr_event import (
    RepoPREventRepository,
    RepoPROpenedEventDenyReason,
    RepoPROpenedEventWriter,
    append_repo_pr_opened_event,
    build_repo_pr_opened_payload,
)
from backend.app.services.repoproxy.repoproxy import (
    DraftPRBinding,
    DraftPRResult,
    RepoProxyDenyReason,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-00000000e001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-00000000e002")
PROJECT_ID = UUID("00000000-0000-4000-8000-00000000e003")
RUN_ID = UUID("00000000-0000-4000-8000-00000000e004")
APPROVAL_ID = UUID("00000000-0000-4000-8000-00000000e005")
HEAD_SHA = "2" * 40
CREATED_AT = datetime(2026, 5, 24, 18, 30, tzinfo=UTC)


class _FakeEventRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def append_event(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        event_type: str,
        event_payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: str | None = None,
        expected_previous_seq_no: int | None = None,
    ) -> AgentRunEvent:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "run_id": run_id,
                "event_type": event_type,
                "event_payload": event_payload,
                "actor_id": actor_id,
                "idempotency_key": idempotency_key,
                "expected_previous_seq_no": expected_previous_seq_no,
            }
        )
        return cast(AgentRunEvent, SimpleNamespace(seq_no=1, event_payload=event_payload))


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-repo-pr-event",
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
    except (OSError, PostgresError, SQLAlchemyError, TimeoutError) as exc:
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError(
                "RepoProxy repo_pr_opened event tests require a reachable test database."
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


async def _setup_runtime_fixture(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              agent_run_events,
              agent_runs,
              projects,
              workspaces,
              actors,
              tenants
            restart identity cascade
            """
        )
    )
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values (1, 'tenant-one', '{"rls_ready": true}'::jsonb)
            """
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values (:actor_id, 1, 'github_app', 'github-app:repo-proxy',
                    'RepoProxy GitHub App', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'repo-workspace', 'repo-workspace',
                    :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (:project_id, 1, :workspace_id, 'repo-project', 'repo-project',
                    'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"project_id": PROJECT_ID, "workspace_id": WORKSPACE_ID},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, status)
            values (:run_id, 1, :project_id, 'running')
            """
        ),
        {"run_id": RUN_ID, "project_id": PROJECT_ID},
    )


def _binding() -> DraftPRBinding:
    return DraftPRBinding(
        tenant_id=TENANT_ID,
        approval_id=APPROVAL_ID,
        agent_run_id=RUN_ID,
    )


def _success_result(
    *,
    pr_number: int | None = 42,
    pr_url: str | None = "https://ghs_leaky_token@example.invalid/owner/repo/pull/42",
    draft: bool = True,
    deny_reason: RepoProxyDenyReason | None = None,
    repo_full_name: str | None = "owner/repo",
    branch: str | None = "codex/agent-run-abcd1234",
    head_sha: str | None = HEAD_SHA,
) -> DraftPRResult:
    return DraftPRResult(
        pr_number=pr_number,
        pr_url=pr_url,
        draft=draft,
        deny_reason=deny_reason,
        repo_full_name=repo_full_name,
        branch=branch,
        head_sha=head_sha,
    )


def test_build_payload_uses_canonical_redacted_pr_url() -> None:
    payload = build_repo_pr_opened_payload(
        binding=_binding(),
        result=_success_result(),
        created_at=CREATED_AT,
    )

    assert not isinstance(payload, RepoPROpenedEventDenyReason)
    assert payload.to_dict() == {
        "pr_number": 42,
        "pr_url": "https://github.com/owner/repo/pull/42",
        "repo_full_name": "owner/repo",
        "branch": "codex/agent-run-abcd1234",
        "head_sha": HEAD_SHA,
        "draft": True,
        "created_at": "2026-05-24T18:30:00+00:00",
        "approval_id": str(APPROVAL_ID),
        "source": "repoproxy",
    }
    assert "ghs_leaky_token" not in repr(payload.to_dict())
    assert_no_raw_secret(payload.to_dict(), path="$repo_pr_opened")


def test_build_payload_denies_failed_or_incomplete_result() -> None:
    denied = build_repo_pr_opened_payload(
        binding=_binding(),
        result=_success_result(
            pr_number=None,
            deny_reason=RepoProxyDenyReason.APPROVAL_NOT_GRANTED,
        ),
        created_at=CREATED_AT,
    )
    incomplete = build_repo_pr_opened_payload(
        binding=_binding(),
        result=_success_result(head_sha="not-a-sha"),
        created_at=CREATED_AT,
    )

    assert denied == RepoPROpenedEventDenyReason.PR_NOT_CREATED
    assert incomplete == RepoPROpenedEventDenyReason.PR_RESULT_INCOMPLETE


@pytest.mark.asyncio
async def test_writer_appends_repo_pr_opened_event_with_idempotency_key() -> None:
    repository = _FakeEventRepository()
    writer = RepoPROpenedEventWriter(
        event_repository=cast(RepoPREventRepository, repository)
    )

    event = await writer.append_from_result(
        binding=_binding(),
        actor_id=ACTOR_ID,
        result=_success_result(),
        created_at=CREATED_AT,
        expected_previous_seq_no=0,
    )
    expected_payload = build_repo_pr_opened_payload(
        binding=_binding(),
        result=_success_result(),
        created_at=CREATED_AT,
    )

    assert not isinstance(event, RepoPROpenedEventDenyReason)
    assert event.seq_no == 1
    assert not isinstance(expected_payload, RepoPROpenedEventDenyReason)
    assert repository.calls == [
        {
            "tenant_id": TENANT_ID,
            "run_id": RUN_ID,
            "event_type": "repo_pr_opened",
            "event_payload": expected_payload.to_dict(),
            "actor_id": ACTOR_ID,
            "idempotency_key": f"repoproxy:repo_pr_opened:{RUN_ID}:42",
            "expected_previous_seq_no": 0,
        }
    ]


@pytest.mark.asyncio
async def test_writer_does_not_append_for_denied_result() -> None:
    repository = _FakeEventRepository()
    writer = RepoPROpenedEventWriter(
        event_repository=cast(RepoPREventRepository, repository)
    )

    result = await writer.append_from_result(
        binding=_binding(),
        actor_id=ACTOR_ID,
        result=_success_result(
            pr_number=None,
            deny_reason=RepoProxyDenyReason.APPROVAL_NOT_GRANTED,
        ),
    )

    assert result == RepoPROpenedEventDenyReason.PR_NOT_CREATED
    assert repository.calls == []


@pytest.mark.asyncio
async def test_append_repo_pr_opened_event_persists_append_only_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        event = await append_repo_pr_opened_event(
            session,
            binding=_binding(),
            actor_id=ACTOR_ID,
            result=_success_result(),
            created_at=CREATED_AT,
            expected_previous_seq_no=0,
        )
        await session.commit()

        assert isinstance(event, AgentRunEvent)
        persisted = await session.scalar(select(AgentRunEvent))
        assert persisted is not None
        assert persisted.event_type == "repo_pr_opened"
        assert persisted.seq_no == 1
        assert persisted.idempotency_key == f"repoproxy:repo_pr_opened:{RUN_ID}:42"
        assert persisted.event_payload["pr_number"] == 42
        assert persisted.event_payload["pr_url"] == "https://github.com/owner/repo/pull/42"
        assert persisted.event_payload["branch"] == "codex/agent-run-abcd1234"
        assert persisted.event_payload["head_sha"] == HEAD_SHA
        assert persisted.event_payload["draft"] is True
        assert "ghs_leaky_token" not in repr(persisted.event_payload)
