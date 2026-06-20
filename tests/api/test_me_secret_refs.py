"""R-3 (ADR-00036) contract test: GET /api/v1/me/secret-refs (read-only inventory).

raw secret / security topology を返さない read-only インベントリ。fast な mapping allowlist
test (DB 不要) と DB-backed test (end-to-end + tenant isolation + 禁止 field 非含有)。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.api.approval_inbox import get_db_session
from backend.app.api.me import (
    SecretRefListItem,
    _to_secret_ref_item,
    list_secret_refs_endpoint,
    require_secret_refs_viewer,
)
from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.main import create_app
from backend.app.middleware.dev_actor import (
    DEV_SESSION_COOKIE_NAME,
    create_signed_session_cookie,
)


def _fake_request(*, authenticated: bool) -> object:
    """gate が参照する `request.state.authenticated` と `request.app.state.settings` を持つ
    最小 fake request (Codex PR #298 P2: gate は app の resolved settings を使う)。
    """
    return SimpleNamespace(
        state=SimpleNamespace(authenticated=authenticated),
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(default_actor_id="human:default")
            )
        ),
    )


def _authenticated_request() -> object:
    return _fake_request(authenticated=True)


def _unauthenticated_request() -> object:
    return _fake_request(authenticated=False)

ACTOR_SERVICE_ID = UUID("00000000-0000-4000-8000-0000000bb002")
ACTOR_AGENT_ID = UUID("00000000-0000-4000-8000-0000000bb003")
ACTOR_EXTRA_HUMAN_ID = UUID("00000000-0000-4000-8000-0000000bb004")
ACTOR_PROVIDER_ID = UUID("00000000-0000-4000-8000-0000000bb005")
ACTOR_GITHUB_APP_ID = UUID("00000000-0000-4000-8000-0000000bb006")

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

ACTOR_ID = UUID("00000000-0000-4000-8000-0000000bb001")
ACTOR_T2_ID = UUID("00000000-0000-4000-8000-0000000bb091")
SECRET_ACTIVE_ID = UUID("00000000-0000-4000-8000-0000000bb010")
SECRET_DEPRECATED_ID = UUID("00000000-0000-4000-8000-0000000bb011")
SECRET_REVOKED_ID = UUID("00000000-0000-4000-8000-0000000bb012")
SECRET_T2_ID = UUID("00000000-0000-4000-8000-0000000bb092")

# response に出してはならない field (Codex plan review R1 HIGH/MEDIUM)
FORBIDDEN_ITEM_FIELDS = {
    "secret_uri",
    "allowed_consumers",
    "allowed_operations",
    "owner_actor_id",
    "runner_injectable",
    "metadata_",
    "metadata",
}
EXPECTED_ITEM_FIELDS = {
    "id",
    "scope",
    "name",
    "version",
    "status",
    "rotated",
    "created_at",
    "updated_at",
    "deprecated_at",
    "revoked_at",
    # broker-owned material lifecycle (ADR-00058 finding-2 / ADR-00059)。非 secret な運用 metadata。
    "material_state",
    "material_purged_at",
    "purge_attempts",
}
_RAW_SECRET_PATTERN = re.compile(
    r"(secret://|sk-[A-Za-z0-9_-]{8,}|api[_-]?key|bearer\s|-----BEGIN)",
    re.IGNORECASE,
)


# --------- fast (no DB): mapping allowlist ---------


def test_secret_ref_list_item_fields_are_allowlisted() -> None:
    """schema は公開 field のみを持ち、禁止 field を持たない (mapping 漏れ防止の型レベル固定)."""
    assert set(SecretRefListItem.model_fields) == EXPECTED_ITEM_FIELDS
    assert FORBIDDEN_ITEM_FIELDS.isdisjoint(set(SecretRefListItem.model_fields))


def test_to_secret_ref_item_excludes_forbidden_metadata() -> None:
    """_to_secret_ref_item は明示 allowlist mapping で security topology を写像しない."""
    now = datetime(2026, 5, 29, tzinfo=UTC)
    fake = SimpleNamespace(
        id=SECRET_ACTIVE_ID,
        secret_uri="secret://sops/provider/provider-openai#v2",
        scope="provider",
        name="provider-openai",
        version="v2",
        status="active",
        runner_injectable=False,
        allowed_consumers=["actor:secret-bb001"],
        allowed_operations=["provider.call"],
        owner_actor_id=ACTOR_ID,
        rotated_from_id=SECRET_DEPRECATED_ID,
        metadata_={"rls_ready": True, "note": "internal"},
        created_at=now,
        updated_at=now,
        deprecated_at=None,
        revoked_at=None,
        material_state="present",
        material_purged_at=None,
        purge_attempts=0,
    )

    item = _to_secret_ref_item(fake)  # type: ignore[arg-type]
    dumped = item.model_dump()

    assert set(dumped.keys()) == EXPECTED_ITEM_FIELDS
    # 公開 field
    assert dumped["scope"] == "provider"
    assert dumped["name"] == "provider-openai"
    assert dumped["version"] == "v2"
    assert dumped["status"] == "active"
    assert dumped["rotated"] is True  # rotated_from_id is not None
    # 禁止 field は dump に存在しない
    for forbidden in FORBIDDEN_ITEM_FIELDS:
        assert forbidden not in dumped
    # secret_uri / consumers / operations / owner の値も漏れない
    serialized = json.dumps(dumped, default=str)
    assert "secret://" not in serialized
    assert "provider.call" not in serialized
    assert "actor:secret-bb001" not in serialized
    assert str(ACTOR_ID) not in serialized


def test_to_secret_ref_item_rotated_false_when_no_predecessor() -> None:
    now = datetime(2026, 5, 29, tzinfo=UTC)
    fake = SimpleNamespace(
        id=SECRET_ACTIVE_ID,
        secret_uri="secret://sops/provider/provider-openai#v1",
        scope="provider",
        name="provider-openai",
        version="v1",
        status="active",
        runner_injectable=False,
        allowed_consumers=["actor:x"],
        allowed_operations=["provider.call"],
        owner_actor_id=ACTOR_ID,
        rotated_from_id=None,
        metadata_={"rls_ready": True},
        created_at=now,
        updated_at=now,
        deprecated_at=None,
        revoked_at=None,
        material_state="present",
        material_purged_at=None,
        purge_attempts=0,
    )
    item = _to_secret_ref_item(fake)  # type: ignore[arg-type]
    assert item.rotated is False


# --------- DB-backed ---------

pytestmark_db = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


_COOKIE_SECRET = "test-cookie-secret-for-secret-refs"


def _integration_settings() -> Settings:
    database_url = os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL)
    redis_url = os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL)
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=database_url,
        redis_url=redis_url,
        dev_login_cookie_secret=_COOKIE_SECRET,
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
            raise AssertionError("secret-refs tests require PostgreSQL.") from exc
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
        text("truncate secret_refs, actors, tenants restart identity cascade")
    )


async def _seed(session: AsyncSession) -> None:
    """tenant 1 (3 secret_refs) + tenant 2 (1 secret_ref) を seed."""
    await session.execute(
        text(
            "insert into tenants (id, name, metadata) values "
            "(1, 'tenant-one', '{\"rls_ready\": true}'::jsonb), "
            "(2, 'tenant-two', '{\"rls_ready\": true}'::jsonb)"
        )
    )
    # ACTOR_ID / ACTOR_T2_ID は各 tenant の P0 owner (stable actor_id = 'human:default')。
    # それ以外 (extra human / service / agent / provider / github_app) は閲覧 gate で 403 になる。
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values
              (:a1, 1, 'human', 'human:default', 'Owner One', '{"rls_ready": true}'::jsonb),
              (:exh, 1, 'human', 'human:other', 'Extra Human', '{"rls_ready": true}'::jsonb),
              (:svc, 1, 'service', 'service:worker1', 'Worker', '{"rls_ready": true}'::jsonb),
              (:agt, 1, 'agent', 'agent:runner1', 'Agent', '{"rls_ready": true}'::jsonb),
              (:prv, 1, 'provider', 'provider:openai', 'Provider', '{"rls_ready": true}'::jsonb),
              (:gha, 1, 'github_app', 'github_app:repo', 'GitHub App', '{"rls_ready": true}'::jsonb),
              (:a2, 2, 'human', 'human:default', 'Owner Two', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "a1": ACTOR_ID,
            "exh": ACTOR_EXTRA_HUMAN_ID,
            "svc": ACTOR_SERVICE_ID,
            "agt": ACTOR_AGENT_ID,
            "prv": ACTOR_PROVIDER_ID,
            "gha": ACTOR_GITHUB_APP_ID,
            "a2": ACTOR_T2_ID,
        },
    )
    # tenant 1: active (rotated from deprecated) + deprecated + revoked
    await session.execute(
        text(
            """
            insert into secret_refs
              (id, tenant_id, secret_uri, scope, name, version, status, runner_injectable,
               allowed_consumers, allowed_operations, owner_actor_id, rotated_from_id, metadata,
               deprecated_at, revoked_at, material_state, material_purged_at)
            values
              (:dep, 1, 'secret://sops/provider/provider-openai#v1', 'provider',
                'provider-openai', 'v1', 'deprecated', false,
                '["actor:owner1"]'::jsonb, '["provider.call"]'::jsonb, :a1, null,
                '{"rls_ready": true}'::jsonb, now(), null, 'present', null),
              (:act, 1, 'secret://sops/provider/provider-openai#v2', 'provider',
                'provider-openai', 'v2', 'active', false,
                '["actor:owner1"]'::jsonb, '["provider.call"]'::jsonb, :a1, :dep,
                '{"rls_ready": true}'::jsonb, null, null, 'present', null),
              (:rev, 1, 'secret://sops/repo/github-app-key#v1', 'repo',
                'github-app-key', 'v1', 'revoked', false,
                '["actor:owner1"]'::jsonb, '["repo.push"]'::jsonb, :a1, null,
                '{"rls_ready": true}'::jsonb, now(), now(), 'purged', now())
            """
        ),
        {"dep": SECRET_DEPRECATED_ID, "act": SECRET_ACTIVE_ID, "rev": SECRET_REVOKED_ID, "a1": ACTOR_ID},
    )
    # tenant 2: 1 active secret_ref (cross-tenant negative 用)
    await session.execute(
        text(
            """
            insert into secret_refs
              (id, tenant_id, secret_uri, scope, name, version, status, runner_injectable,
               allowed_consumers, allowed_operations, owner_actor_id, rotated_from_id, metadata,
               deprecated_at, revoked_at, material_state, material_purged_at)
            values
              (:t2, 2, 'secret://sops/provider/provider-anthropic#v1', 'provider',
                'provider-anthropic', 'v1', 'active', false,
                '["actor:owner2"]'::jsonb, '["provider.call"]'::jsonb, :a2, null,
                '{"rls_ready": true}'::jsonb, null, null, 'present', null)
            """
        ),
        {"t2": SECRET_T2_ID, "a2": ACTOR_T2_ID},
    )
    await session.commit()


@pytestmark_db
@pytest.mark.asyncio
async def test_list_secret_refs_returns_allowlisted_metadata(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)

    async with session_factory() as session:
        response = await list_secret_refs_endpoint(viewer_actor_id=ACTOR_ID, tenant_id=1, session=session)

    # tenant 1 の 3 件のみ。order: scope (provider, provider, repo) -> name -> version
    items = response.secret_refs
    assert len(items) == 3
    by_name_ver = {(i.scope, i.name, i.version): i for i in items}

    active = by_name_ver[("provider", "provider-openai", "v2")]
    assert active.status == "active"
    assert active.rotated is True  # rotated_from_id set
    assert active.deprecated_at is None
    assert active.revoked_at is None

    deprecated = by_name_ver[("provider", "provider-openai", "v1")]
    assert deprecated.status == "deprecated"
    assert deprecated.rotated is False
    assert deprecated.deprecated_at is not None

    revoked = by_name_ver[("repo", "github-app-key", "v1")]
    assert revoked.status == "revoked"
    assert revoked.revoked_at is not None

    # 各 item は公開 field のみ
    for item in items:
        assert set(item.model_dump().keys()) == EXPECTED_ITEM_FIELDS


@pytestmark_db
@pytest.mark.asyncio
async def test_list_secret_refs_excludes_topology_and_raw_secret(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)

    async with session_factory() as session:
        response = await list_secret_refs_endpoint(viewer_actor_id=ACTOR_ID, tenant_id=1, session=session)

    serialized = response.model_dump_json()
    # security topology / raw secret 系が response に含まれない
    assert "secret://" not in serialized  # secret_uri 非露出
    assert "allowed_consumers" not in serialized
    assert "allowed_operations" not in serialized
    assert "provider.call" not in serialized
    assert "repo.push" not in serialized
    assert "owner_actor_id" not in serialized
    assert str(ACTOR_ID) not in serialized
    assert "metadata" not in serialized
    assert "runner_injectable" not in serialized
    assert not _RAW_SECRET_PATTERN.search(serialized)


@pytestmark_db
@pytest.mark.asyncio
async def test_list_secret_refs_is_tenant_scoped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """tenant 1 で呼ぶと tenant 2 の secret_ref を返さない (cross-tenant negative)."""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)

    async with session_factory() as session:
        response = await list_secret_refs_endpoint(viewer_actor_id=ACTOR_ID, tenant_id=1, session=session)

    names = {(i.scope, i.name) for i in response.secret_refs}
    assert ("provider", "provider-anthropic") not in names  # tenant 2 の鍵
    assert all(i.id != SECRET_T2_ID for i in response.secret_refs)

    # tenant 2 で呼ぶと tenant 2 の 1 件のみ
    async with session_factory() as session:
        response_t2 = await list_secret_refs_endpoint(viewer_actor_id=ACTOR_T2_ID, tenant_id=2, session=session)
    assert len(response_t2.secret_refs) == 1
    assert response_t2.secret_refs[0].name == "provider-anthropic"


@pytestmark_db
@pytest.mark.asyncio
async def test_list_secret_refs_empty_tenant_returns_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _reset_tables(session)
        # tenant のみ (secret_ref なし)
        await session.execute(
            text(
                "insert into tenants (id, name, metadata) "
                "values (1, 'tenant-one', '{\"rls_ready\": true}'::jsonb)"
            )
        )
        await session.commit()

    async with session_factory() as session:
        response = await list_secret_refs_endpoint(viewer_actor_id=ACTOR_ID, tenant_id=1, session=session)

    assert response.secret_refs == []


@pytestmark_db
@pytest.mark.asyncio
async def test_require_secret_refs_viewer_allows_authenticated_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex R1/R2/R3 (HIGH): 認証済み session の P0 owner (human:default) は許可される."""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)

    async with session_factory() as session:
        resolved = await require_secret_refs_viewer(
            _authenticated_request(),  # type: ignore[arg-type]
            actor_id=ACTOR_ID,
            tenant_id=1,
            session=session,
        )
        assert resolved == ACTOR_ID


@pytestmark_db
@pytest.mark.asyncio
async def test_require_secret_refs_viewer_rejects_unauthenticated_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex R3 (HIGH): 認証されていない (dev/test fallback authenticated=False) request は、
    たとえ default owner actor として resolve されても 401 で弾く (fail-closed)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)

    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await require_secret_refs_viewer(
                _unauthenticated_request(),  # type: ignore[arg-type]
                actor_id=ACTOR_ID,  # default owner として resolve されても
                tenant_id=1,
                session=session,
            )
        assert exc_info.value.status_code == 401


@pytestmark_db
@pytest.mark.asyncio
async def test_require_secret_refs_viewer_rejects_non_owner_actors(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex R1/R2 (HIGH): 認証済みでも P0 owner 以外は 403 で fail-closed.

    同一 tenant の **別 human (非 owner)**、service / agent / provider / github_app actor は
    いずれも secret inventory を列挙できない (owner-only を実装で enforce)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)

    non_owner_actors = (
        ACTOR_EXTRA_HUMAN_ID,  # 同一 tenant の別 human (R2 の核心ケース)
        ACTOR_SERVICE_ID,
        ACTOR_AGENT_ID,
        ACTOR_PROVIDER_ID,
        ACTOR_GITHUB_APP_ID,
    )
    for non_owner_actor in non_owner_actors:
        async with session_factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await require_secret_refs_viewer(
                    _authenticated_request(),  # type: ignore[arg-type]
                    actor_id=non_owner_actor,
                    tenant_id=1,
                    session=session,
                )
            assert exc_info.value.status_code == 403


@pytestmark_db
@pytest.mark.asyncio
async def test_secret_refs_route_rejects_no_cookie_request(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Codex R3 (HIGH) route-level: cookie 無し request (dev/test fallback) は列挙できない.

    create_app (environment=test) 経由で、cookie 無し GET /api/v1/me/secret-refs が 401/403 に
    なることを end-to-end で確認 (middleware が authenticated=False を seed し gate が弾く)。
    """
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)

    app = create_app(_integration_settings())

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/me/secret-refs")

    assert response.status_code in (401, 403)


@pytestmark_db
@pytest.mark.asyncio
async def test_secret_refs_route_allows_owner_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """route-level: 有効な owner session cookie では 200 + インベントリを返し、raw secret を出さない."""
    async with session_factory() as session:
        await _reset_tables(session)
        await _seed(session)

    app = create_app(_integration_settings())

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_session
    cookie_value, _expires = create_signed_session_cookie(secret=_COOKIE_SECRET)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={DEV_SESSION_COOKIE_NAME: cookie_value},
    ) as client:
        response = await client.get("/api/v1/me/secret-refs")

    assert response.status_code == 200
    body = response.text
    # tenant 1 の secret_refs を返す
    payload = response.json()
    assert len(payload["secret_refs"]) == 3
    # raw secret / security topology は出さない
    assert "secret://" not in body
    assert "allowed_consumers" not in body
    assert "owner_actor_id" not in body
    assert not _RAW_SECRET_PATTERN.search(body)
