"""SP-014 batch 0d: Tool Registry network enum and policy tests."""

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
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.domain.tool_registry.network_policy import (
    ALL_NETWORK_ACCESS_MODES,
    ALL_PAYLOAD_DATA_CLASSES,
    DEFAULT_DENY_ONLY_TOOL_KEYS,
)
from backend.app.services.tool_registry.network_policy import evaluate_tool_network_policy

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)

TENANT_ID = 1
TRIGGER_TENANT_ID = 78
ALLOWLIST_TOOL_ID = UUID("00000000-0000-4000-8000-000000028001")
INTERNET_TOOL_ID = UUID("00000000-0000-4000-8000-000000028002")


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-tool-registry",
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
            raise AssertionError("tool registry tests require PostgreSQL.") from exc
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


async def _reset_test_tools(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            delete from tool_network_policies
             where tenant_id = 1
               and tool_id in (:allowlist_tool_id, :internet_tool_id)
            """
        ),
        {
            "allowlist_tool_id": ALLOWLIST_TOOL_ID,
            "internet_tool_id": INTERNET_TOOL_ID,
        },
    )
    await session.execute(
        text(
            """
            delete from tool_registry
             where tenant_id = 1
               and id in (:allowlist_tool_id, :internet_tool_id)
            """
        ),
        {
            "allowlist_tool_id": ALLOWLIST_TOOL_ID,
            "internet_tool_id": INTERNET_TOOL_ID,
        },
    )


def test_network_enum_source_constants_are_exact() -> None:
    assert ALL_NETWORK_ACCESS_MODES == {"none", "allowlist", "internet"}
    assert ALL_PAYLOAD_DATA_CLASSES == {"public", "internal", "confidential", "pii"}
    assert DEFAULT_DENY_ONLY_TOOL_KEYS == ("web_fetch", "docs_search")


@pytest.mark.asyncio
async def test_default_web_fetch_and_docs_search_are_seeded_deny_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    select tool_key, network_access, registry_version,
                           allowed_actions, max_outgoing_data_class,
                           manifest->>'deny_only' as deny_only
                      from tool_registry
                     where tenant_id = 1
                       and tool_key in ('web_fetch', 'docs_search')
                     order by tool_key
                    """
                )
            )
        ).all()

    assert [
        (
            row.tool_key,
            row.network_access,
            row.registry_version,
            row.allowed_actions,
            row.max_outgoing_data_class,
            row.deny_only,
        )
        for row in rows
    ] == [
        ("docs_search", "none", "sp0045-v1", ["docs_search"], "public", "true"),
        ("web_fetch", "none", "sp0045-v1", ["web_fetch"], "public", "true"),
    ]


@pytest.mark.asyncio
async def test_new_tenant_insert_seeds_default_deny_only_tools(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("delete from tool_network_policies where tenant_id = :tenant_id"),
                {"tenant_id": TRIGGER_TENANT_ID},
            )
            await session.execute(
                text("delete from tool_registry where tenant_id = :tenant_id"),
                {"tenant_id": TRIGGER_TENANT_ID},
            )
            await session.execute(
                text("delete from tenants where id = :tenant_id"),
                {"tenant_id": TRIGGER_TENANT_ID},
            )
            await session.execute(
                text(
                    """
                    insert into tenants (id, name, metadata)
                    values (:tenant_id, 'trigger-tool-registry-tenant',
                            '{"rls_ready": true}'::jsonb)
                    """
                ),
                {"tenant_id": TRIGGER_TENANT_ID},
            )

        rows = (
            await session.execute(
                text(
                    """
                    select tool_key, network_access, registry_version, allowed_actions
                      from tool_registry
                     where tenant_id = :tenant_id
                     order by tool_key
                    """
                ),
                {"tenant_id": TRIGGER_TENANT_ID},
            )
        ).all()

    assert [
        (row.tool_key, row.network_access, row.registry_version, row.allowed_actions)
        for row in rows
    ] == [
        ("docs_search", "none", "sp0045-v1", ["docs_search"]),
        ("web_fetch", "none", "sp0045-v1", ["web_fetch"]),
    ]


@pytest.mark.asyncio
async def test_web_fetch_denies_network_until_allowlist_enabled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        decision = await evaluate_tool_network_policy(
            session,
            tenant_id=TENANT_ID,
            tool_key="web_fetch",
            domain="example.com",
            payload_data_class="public",
        )

    assert decision.decision == "deny"
    assert decision.network_access == "none"
    assert decision.reason_code == "tool_network_access_none_denied"


@pytest.mark.asyncio
async def test_allowlist_policy_allows_only_matching_domain_payload_and_provider(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _reset_test_tools(session)
            await session.execute(
                text(
                    """
                    insert into tool_registry (
                      id, tenant_id, tool_key, transport, auth_mode, network_access,
                      trust_tier, registry_version, allowed_actions,
                      max_outgoing_data_class, manifest, metadata
                    )
                    values (
                      :tool_id, 1, 'allowlisted_fetch', 'local', 'none', 'allowlist',
                      'official', 'sp0045-test', '["web_fetch"]'::jsonb, 'internal',
                      '{"allowed_actions":["web_fetch"]}'::jsonb,
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"tool_id": ALLOWLIST_TOOL_ID},
            )
            await session.execute(
                text(
                    """
                    insert into tool_network_policies (
                      tenant_id, tool_id, domain_allowlist, payload_data_class_max,
                      provider_required, metadata
                    )
                    values (
                      1, :tool_id, '["docs.example.com"]'::jsonb, 'internal',
                      true, '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"tool_id": ALLOWLIST_TOOL_ID},
            )

        allowed = await evaluate_tool_network_policy(
            session,
            tenant_id=TENANT_ID,
            tool_key="allowlisted_fetch",
            domain="DOCS.EXAMPLE.COM.",
            payload_data_class="internal",
            provider="docs-provider",
        )
        wrong_domain = await evaluate_tool_network_policy(
            session,
            tenant_id=TENANT_ID,
            tool_key="allowlisted_fetch",
            domain="evil.example.com",
            payload_data_class="internal",
            provider="docs-provider",
        )
        too_sensitive = await evaluate_tool_network_policy(
            session,
            tenant_id=TENANT_ID,
            tool_key="allowlisted_fetch",
            domain="docs.example.com",
            payload_data_class="confidential",
            provider="docs-provider",
        )
        missing_provider = await evaluate_tool_network_policy(
            session,
            tenant_id=TENANT_ID,
            tool_key="allowlisted_fetch",
            domain="docs.example.com",
            payload_data_class="internal",
        )

    assert allowed.decision == "allow"
    assert allowed.reason_code == "tool_network_allowlist_allowed"
    assert wrong_domain.reason_code == "tool_network_domain_not_allowlisted"
    assert too_sensitive.reason_code == "tool_network_payload_data_class_exceeded"
    assert missing_provider.reason_code == "tool_network_provider_required"


@pytest.mark.asyncio
async def test_internet_mode_is_registered_but_denied_in_p0(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _reset_test_tools(session)
            await session.execute(
                text(
                    """
                    insert into tool_registry (
                      id, tenant_id, tool_key, transport, auth_mode, network_access,
                      trust_tier, registry_version, allowed_actions,
                      max_outgoing_data_class, manifest, metadata
                    )
                    values (
                      :tool_id, 1, 'internet_fetch', 'local', 'none', 'internet',
                      'official', 'sp0045-test', '["web_fetch"]'::jsonb, 'public',
                      '{"allowed_actions":["web_fetch"]}'::jsonb,
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"tool_id": INTERNET_TOOL_ID},
            )

        decision = await evaluate_tool_network_policy(
            session,
            tenant_id=TENANT_ID,
            tool_key="internet_fetch",
            domain="example.com",
            payload_data_class="public",
        )

    assert decision.decision == "deny"
    assert decision.reason_code == "tool_network_internet_denied"


@pytest.mark.asyncio
async def test_db_rejects_unknown_network_access(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _reset_test_tools(session)

        with pytest.raises(DBAPIError, match="tool_registry_ck_network_access"):
            await session.execute(
                text(
                    """
                    insert into tool_registry (
                      tenant_id, tool_key, transport, auth_mode, network_access,
                      trust_tier, registry_version, allowed_actions,
                      max_outgoing_data_class, manifest, metadata
                    )
                    values (
                      1, 'bad_network_tool', 'local', 'none', 'external',
                      'official', 'sp0045-test', '["web_fetch"]'::jsonb, 'public',
                      '{}'::jsonb, '{"rls_ready": true}'::jsonb
                    )
                    """
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_db_rejects_unknown_allowed_action(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _reset_test_tools(session)

        with pytest.raises(DBAPIError, match="tool_registry_ck_allowed_actions"):
            await session.execute(
                text(
                    """
                    insert into tool_registry (
                      tenant_id, tool_key, transport, auth_mode, network_access,
                      trust_tier, registry_version, allowed_actions,
                      max_outgoing_data_class, manifest, metadata
                    )
                    values (
                      1, 'bad_action_tool', 'local', 'none', 'none',
                      'official', 'sp0045-test', '["repo_write"]'::jsonb, 'public',
                      '{}'::jsonb, '{"rls_ready": true}'::jsonb
                    )
                    """
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_tool_versions_rejects_non_sha_allowlist_hash(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _reset_test_tools(session)
            await session.execute(
                text(
                    """
                    insert into tool_registry (
                      id, tenant_id, tool_key, transport, auth_mode, network_access,
                      trust_tier, registry_version, allowed_actions,
                      max_outgoing_data_class, manifest, metadata
                    )
                    values (
                      :tool_id, 1, 'allowlisted_fetch', 'local', 'none', 'none',
                      'official', 'sp0045-test', '["web_fetch"]'::jsonb, 'public',
                      '{"allowed_actions":["web_fetch"]}'::jsonb,
                      '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"tool_id": ALLOWLIST_TOOL_ID},
            )

        with pytest.raises(DBAPIError, match="tool_versions_ck_allowlist_hash"):
            await session.execute(
                text(
                    """
                    insert into tool_versions (
                      tenant_id, tool_id, registry_version, allowlist_hash,
                      manifest, metadata
                    )
                    values (
                      1, :tool_id, 'sp0045-test', 'not-a-sha',
                      '{}'::jsonb, '{"rls_ready": true}'::jsonb
                    )
                    """
                ),
                {"tool_id": ALLOWLIST_TOOL_ID},
            )
            await session.commit()
