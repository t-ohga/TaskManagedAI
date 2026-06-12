"""ADR-00050 (SP-028) webhook event parser + read repository の DB-backed contract test。

persist / dedup / hash anomaly / quarantine / FK SET NULL / read project-scope を実 PostgreSQL で固定。
DB 接続必要: TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container 起動時のみ実行 (host では skip)。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.models.github_webhook_event import GitHubWebhookEvent
from backend.app.db.models.repository import Repository
from backend.app.db.session import create_engine
from backend.app.repositories.github_webhook_event import GitHubWebhookEventRepository
from backend.app.seeds.initial import (
    DEFAULT_PROJECT_ID,
    DEFAULT_REPOSITORY_EXTERNAL_ID,
    DEFAULT_TENANT_ID,
    seed_initial,
)
from backend.app.services.repoproxy.webhook_event_parser import (
    WEBHOOK_DELIVERY_HASH_MISMATCH_AUDIT_EVENT_TYPE,
    WebhookEventOutcome,
    record_webhook_event,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALLATION_ID = 4242

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


def _integration_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-webhook-events",
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
            raise AssertionError("webhook event test requires PostgreSQL.") from exc
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
    # seed_initial は呼び出し側 commit 前提。begin() で確実に commit し、repository
    # (external_id=DEFAULT_REPOSITORY_EXTERNAL_ID) を含む seed を永続化する (未 commit だと webhook が
    # repo 解決できず unregistered_repo quarantine になる)。github_webhook_events は per-test に reset
    # して event 蓄積で idempotency/一覧 test が混ざるのを防ぐ (repo は seed が毎回再作成)。
    async with factory.begin() as session:
        await session.execute(
            text("truncate github_webhook_events, audit_events restart identity cascade")
        )
        await seed_initial(session)
    try:
        yield factory
    finally:
        await engine.dispose()


def _pr_payload(*, repo_id: int, number: int = 1, title: str = "Fix bug") -> bytes:
    return json.dumps(
        {
            "action": "opened",
            "pull_request": {"number": number, "state": "open", "title": title, "merged": False},
            "sender": {"login": "octocat"},
            "repository": {"id": repo_id},
        }
    ).encode("utf-8")


async def _record(
    factory: async_sessionmaker[AsyncSession],
    *,
    delivery_id: str,
    payload: bytes,
    event_kind: str = "pull_request",
) -> WebhookEventOutcome:
    async with factory() as session:
        return await record_webhook_event(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            installation_id=_INSTALLATION_ID,
            delivery_id=delivery_id,
            event_kind_header=event_kind,
            payload=payload,
            payload_hash=hashlib.sha256(payload).hexdigest(),
        )


async def _default_repo_id(factory: async_sessionmaker[AsyncSession]) -> UUID:
    async with factory() as session:
        repo_id = await session.scalar(
            select(Repository.id).where(
                Repository.tenant_id == DEFAULT_TENANT_ID,
                Repository.provider == "github",
                Repository.external_id == DEFAULT_REPOSITORY_EXTERNAL_ID,
            )
        )
    assert repo_id is not None
    return repo_id


@pytest.mark.asyncio
async def test_accepted_event_persisted_with_repository(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo_external_id = int(DEFAULT_REPOSITORY_EXTERNAL_ID)
    outcome = await _record(
        session_factory,
        delivery_id=f"d-{uuid4()}",
        payload=_pr_payload(repo_id=repo_external_id, title="Land feature"),
    )
    assert outcome.status == "accepted"
    repo_id = await _default_repo_id(session_factory)
    async with session_factory() as session:
        row = (
            await session.execute(
                select(GitHubWebhookEvent).where(
                    GitHubWebhookEvent.event_kind == "pull_request",
                    GitHubWebhookEvent.title == "Land feature",
                )
            )
        ).scalar_one()
    assert row.status == "accepted"
    assert row.repository_id == repo_id
    assert row.quarantine_reason is None
    assert row.external_ref == "1"
    assert row.state == "open"


@pytest.mark.asyncio
async def test_unregistered_repo_is_quarantined(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    outcome = await _record(
        session_factory,
        delivery_id=f"d-{uuid4()}",
        payload=_pr_payload(repo_id=999999, title="Unknown repo PR"),
    )
    assert outcome.status == "quarantined"
    async with session_factory() as session:
        row = (
            await session.execute(
                select(GitHubWebhookEvent).where(GitHubWebhookEvent.title == "Unknown repo PR")
            )
        ).scalar_one()
    assert row.status == "quarantined"
    assert row.quarantine_reason == "unregistered_repo"
    assert row.repository_id is None


@pytest.mark.asyncio
async def test_redelivery_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    delivery_id = f"d-{uuid4()}"
    payload = _pr_payload(repo_id=int(DEFAULT_REPOSITORY_EXTERNAL_ID), title="Idem PR")
    first = await _record(session_factory, delivery_id=delivery_id, payload=payload)
    second = await _record(session_factory, delivery_id=delivery_id, payload=payload)
    assert first.status == "accepted"
    assert second.status == "idempotent"
    async with session_factory() as session:
        count = await session.scalar(
            select(text("count(*)")).select_from(GitHubWebhookEvent).where(
                GitHubWebhookEvent.delivery_id == delivery_id
            )
        )
    assert count == 1


@pytest.mark.asyncio
async def test_same_delivery_different_body_is_audited_not_stored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    delivery_id = f"d-{uuid4()}"
    repo_id = int(DEFAULT_REPOSITORY_EXTERNAL_ID)
    first = await _record(
        session_factory, delivery_id=delivery_id, payload=_pr_payload(repo_id=repo_id, title="orig")
    )
    second = await _record(
        session_factory,
        delivery_id=delivery_id,
        payload=_pr_payload(repo_id=repo_id, title="tampered"),
    )
    assert first.status == "accepted"
    assert second.status == "anomaly"
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(GitHubWebhookEvent).where(GitHubWebhookEvent.delivery_id == delivery_id)
            )
        ).scalars().all()
        # 既存 row のみ保持 (新 body は row 化されない)、title は元のまま。
        assert len(rows) == 1
        assert rows[0].title == "orig"
        anomaly_count = await session.scalar(
            text(
                "select count(*) from audit_events where event_type = :t"
            ),
            {"t": WEBHOOK_DELIVERY_HASH_MISMATCH_AUDIT_EVENT_TYPE},
        )
    assert anomaly_count == 1


@pytest.mark.asyncio
async def test_invalid_json_is_quarantined_parse_validation_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    outcome = await _record(
        session_factory, delivery_id=f"d-{uuid4()}", payload=b"{not json"
    )
    assert outcome.status == "quarantined"
    assert outcome.quarantine_reason == "parse_validation_failed"


@pytest.mark.asyncio
async def test_shape_mismatch_is_quarantined(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # header=pull_request だが pull_request key 欠落
    payload = json.dumps({"action": "opened", "repository": {"id": 1}}).encode("utf-8")
    outcome = await _record(session_factory, delivery_id=f"d-{uuid4()}", payload=payload)
    assert outcome.status == "quarantined"
    assert outcome.quarantine_reason == "payload_shape_mismatch"


@pytest.mark.asyncio
async def test_untracked_event_kind_is_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    outcome = await _record(
        session_factory,
        delivery_id=f"d-{uuid4()}",
        payload=json.dumps({"issue": {"number": 1}}).encode("utf-8"),
        event_kind="issues",
    )
    assert outcome.status == "skipped"
    async with session_factory() as session:
        count = await session.scalar(text("select count(*) from github_webhook_events"))
    assert count == 0


@pytest.mark.asyncio
async def test_db_check_rejects_invalid_event_kind(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "insert into github_webhook_events "
                    "(id, tenant_id, delivery_id, payload_hash, event_kind, status, received_at) "
                    "values (gen_random_uuid(), :t, :d, :h, 'issues', 'accepted', now())"
                ),
                {"t": DEFAULT_TENANT_ID, "d": f"d-{uuid4()}", "h": "x"},
            )
            await session.commit()


@pytest.mark.asyncio
async def test_db_check_rejects_quarantined_without_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "insert into github_webhook_events "
                    "(id, tenant_id, delivery_id, payload_hash, event_kind, status, received_at) "
                    "values (gen_random_uuid(), :t, :d, :h, 'push', 'quarantined', now())"
                ),
                {"t": DEFAULT_TENANT_ID, "d": f"d-{uuid4()}", "h": "x"},
            )
            await session.commit()


@pytest.mark.asyncio
async def test_repository_delete_sets_repository_id_null_keeps_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo_id = int(DEFAULT_REPOSITORY_EXTERNAL_ID)
    await _record(
        session_factory,
        delivery_id=f"d-{uuid4()}",
        payload=_pr_payload(repo_id=repo_id, title="FK target"),
    )
    async with session_factory() as session:
        # repository を削除 → column-list ON DELETE SET NULL (repository_id) で repository_id だけ NULL。
        await session.execute(
            text(
                "delete from repositories where tenant_id = :t and provider = 'github' "
                "and external_id = :e"
            ),
            {"t": DEFAULT_TENANT_ID, "e": DEFAULT_REPOSITORY_EXTERNAL_ID},
        )
        await session.commit()
    async with session_factory() as session:
        row = (
            await session.execute(
                select(GitHubWebhookEvent).where(GitHubWebhookEvent.title == "FK target")
            )
        ).scalar_one()
    assert row.repository_id is None
    assert row.tenant_id == DEFAULT_TENANT_ID  # tenant_id は NULL 化されない (R1 F-003)


@pytest.mark.asyncio
async def test_read_feed_returns_accepted_excludes_quarantine(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo_id = int(DEFAULT_REPOSITORY_EXTERNAL_ID)
    await _record(
        session_factory, delivery_id=f"d-{uuid4()}", payload=_pr_payload(repo_id=repo_id, title="Visible")
    )
    await _record(
        session_factory,
        delivery_id=f"d-{uuid4()}",
        payload=_pr_payload(repo_id=999999, title="Quarantined"),
    )
    async with session_factory() as session:
        events = await GitHubWebhookEventRepository(session).list_accepted_for_project(
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            limit=50,
        )
    titles = {e.title for e in events}
    assert "Visible" in titles
    assert "Quarantined" not in titles  # quarantine (repository_id NULL) は join で除外
    assert all(e.status == "accepted" for e in events)


@pytest.mark.asyncio
async def test_read_feed_other_project_filter_returns_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo_id = int(DEFAULT_REPOSITORY_EXTERNAL_ID)
    await _record(
        session_factory, delivery_id=f"d-{uuid4()}", payload=_pr_payload(repo_id=repo_id, title="P1 only")
    )
    other_project = UUID("00000000-0000-4000-8000-0000000009ff")
    async with session_factory() as session:
        events = await GitHubWebhookEventRepository(session).list_accepted_for_project(
            tenant_id=DEFAULT_TENANT_ID,
            project_id=other_project,
            limit=50,
        )
    assert events == []  # 別 project では当該 repo の event を返さない (cross-project leak 防止)
