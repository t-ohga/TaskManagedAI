from __future__ import annotations

import ast
import asyncio
import json
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, get_args
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.domain.artifact.data_class import (
    ALL_PAYLOAD_DATA_CLASSES,
    PayloadDataClass,
)
from backend.app.repositories.artifact import (
    _PROHIBITED_PAYLOAD_KEYS,
    _RAW_SECRET_PATTERNS,
    ArtifactRepository,
    calculate_content_hash,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACTS_MIGRATION = _REPO_ROOT / "migrations" / "versions" / "0009_artifacts_context_snapshots.py"

TENANT_ONE_ACTOR_ID = UUID("00000000-0000-4000-8000-000000007001")
TENANT_TWO_ACTOR_ID = UUID("00000000-0000-4000-8000-000000007002")
TENANT_ONE_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000007011")
TENANT_TWO_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000007012")
TENANT_ONE_PROJECT_ID = UUID("00000000-0000-4000-8000-000000007021")
TENANT_TWO_PROJECT_ID = UUID("00000000-0000-4000-8000-000000007022")
TENANT_ONE_RUN_A_ID = UUID("00000000-0000-4000-8000-000000007031")
TENANT_ONE_RUN_B_ID = UUID("00000000-0000-4000-8000-000000007032")
TENANT_TWO_RUN_ID = UUID("00000000-0000-4000-8000-000000007033")
PARENT_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000007041")

_EXPECTED_PROHIBITED_PAYLOAD_KEYS = frozenset(
    {
        "api_key",
        "api_token",
        "raw_secret",
        "secret",
        "secret_value",
        "private_key",
        "auth_token",
        "bearer_token",
        "capability_token",
        "capability_token_value",
        "provider_key",
        "github_installation_token",
        "github_app_private_key",
        "tailscale_auth_key",
        "sops_age_key",
        "age_private_key",
        "canary_value",
        "raw_canary",
        "secret_capability_token",
        "raw_token",
        "session_token",
    }
)


class _DummySession:
    pass


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-artifact-tests",
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
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        if os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") == "1":
            raise AssertionError("Artifact tests require a reachable test database.") from exc
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


def _call_keyword_string(node: ast.Call, keyword_name: str) -> str | None:
    for keyword in node.keywords:
        if (
            keyword.arg == keyword_name
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ):
            return keyword.value.value
    return None


def _check_constraint_values_from_migration(constraint_name: str) -> set[str]:
    module = ast.parse(_ARTIFACTS_MIGRATION.read_text(encoding="utf-8"))

    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "CheckConstraint":
            continue
        if _call_keyword_string(node, "name") != constraint_name:
            continue
        if not node.args:
            raise AssertionError(f"{constraint_name} has no SQL expression.")
        expression_node = node.args[0]
        if not isinstance(expression_node, ast.Constant) or not isinstance(
            expression_node.value,
            str,
        ):
            raise AssertionError(f"{constraint_name} SQL expression must be a string literal.")
        return set(re.findall(r"'([^']+)'", expression_node.value))

    raise AssertionError(f"{constraint_name} was not found in 0009 migration.")


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
        for arg in getattr(current, "args", ()):
            if isinstance(arg, BaseException):
                queue.append(arg)
    return None


def _assert_integrity_error(
    error: IntegrityError,
    *,
    sqlstate: str,
    constraint_name: str,
) -> None:
    assert _sqlstate(error) == sqlstate
    actual_constraint_name = (
        getattr(error.orig, 'constraint_name', None)
        or getattr(getattr(error.orig, '__cause__', None), 'constraint_name', None)
    )
    assert actual_constraint_name == constraint_name


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              context_snapshots,
              artifacts,
              agent_run_events,
              agent_runs,
              secret_capability_tokens,
              secret_refs,
              notification_events,
              audit_events,
              ticket_relations,
              acceptance_criteria,
              tickets,
              repositories,
              projects,
              workspaces,
              principals,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _setup_runtime_fixture(session: AsyncSession) -> None:
    await _reset_tables(session)
    await session.execute(
        text(
            """
            insert into tenants (id, name, metadata)
            values
              (1, 'tenant-one', '{"rls_ready": true}'::jsonb),
              (2, 'tenant-two', '{"rls_ready": true}'::jsonb)
            """
        )
    )
    await session.execute(
        text(
            """
            insert into actors (id, tenant_id, actor_type, actor_id, display_name, metadata)
            values
              (:tenant_one_actor_id, 1, 'human', 'human:artifact-tenant-one',
                'Artifact Tenant One Actor', '{"rls_ready": true}'::jsonb),
              (:tenant_two_actor_id, 2, 'human', 'human:artifact-tenant-two',
                'Artifact Tenant Two Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "tenant_one_actor_id": TENANT_ONE_ACTOR_ID,
            "tenant_two_actor_id": TENANT_TWO_ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values
              (:tenant_one_workspace_id, 1, 'artifact-workspace-one',
                'artifact-workspace-one', :tenant_one_actor_id,
                '{"rls_ready": true}'::jsonb),
              (:tenant_two_workspace_id, 2, 'artifact-workspace-two',
                'artifact-workspace-two', :tenant_two_actor_id,
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "tenant_one_workspace_id": TENANT_ONE_WORKSPACE_ID,
            "tenant_two_workspace_id": TENANT_TWO_WORKSPACE_ID,
            "tenant_one_actor_id": TENANT_ONE_ACTOR_ID,
            "tenant_two_actor_id": TENANT_TWO_ACTOR_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:tenant_one_project_id, 1, :tenant_one_workspace_id,
                'artifact-project-one', 'artifact-project-one', 'active',
                '{"rls_ready": true}'::jsonb),
              (:tenant_two_project_id, 2, :tenant_two_workspace_id,
                'artifact-project-two', 'artifact-project-two', 'active',
                '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "tenant_one_project_id": TENANT_ONE_PROJECT_ID,
            "tenant_two_project_id": TENANT_TWO_PROJECT_ID,
            "tenant_one_workspace_id": TENANT_ONE_WORKSPACE_ID,
            "tenant_two_workspace_id": TENANT_TWO_WORKSPACE_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, status)
            values
              (:run_a_id, 1, :tenant_one_project_id, 'queued'),
              (:run_b_id, 1, :tenant_one_project_id, 'queued'),
              (:tenant_two_run_id, 2, :tenant_two_project_id, 'queued')
            """
        ),
        {
            "run_a_id": TENANT_ONE_RUN_A_ID,
            "run_b_id": TENANT_ONE_RUN_B_ID,
            "tenant_two_run_id": TENANT_TWO_RUN_ID,
            "tenant_one_project_id": TENANT_ONE_PROJECT_ID,
            "tenant_two_project_id": TENANT_TWO_PROJECT_ID,
        },
    )


async def _insert_artifact(
    session: AsyncSession,
    *,
    artifact_id: UUID | None = None,
    tenant_id: int = 1,
    run_id: UUID = TENANT_ONE_RUN_A_ID,
    kind: str = "plan",
    content_jsonb: dict[str, Any] | None = None,
    content_hash: str | None = None,
    payload_data_class: str = "internal",
    exportable: bool = True,
    parent_artifact_id: UUID | None = None,
) -> UUID:
    artifact_id = artifact_id or uuid4()
    content_jsonb = content_jsonb or {"summary": "redacted"}
    content_hash = content_hash or calculate_content_hash(content_jsonb)
    await session.execute(
        text(
            """
            insert into artifacts (
              id,
              tenant_id,
              run_id,
              kind,
              content_hash,
              content_jsonb,
              payload_data_class,
              exportable,
              parent_artifact_id
            )
            values (
              :artifact_id,
              :tenant_id,
              :run_id,
              :kind,
              :content_hash,
              cast(:content_jsonb as jsonb),
              :payload_data_class,
              :exportable,
              :parent_artifact_id
            )
            """
        ),
        {
            "artifact_id": artifact_id,
            "tenant_id": tenant_id,
            "run_id": run_id,
            "kind": kind,
            "content_hash": content_hash,
            "content_jsonb": json.dumps(content_jsonb),
            "payload_data_class": payload_data_class,
            "exportable": exportable,
            "parent_artifact_id": parent_artifact_id,
        },
    )
    return artifact_id


@pytest.mark.asyncio
async def test_artifact_repository_is_immutable() -> None:
    repo = ArtifactRepository(_DummySession())  # type: ignore[arg-type]

    with pytest.raises(NotImplementedError, match="immutable"):
        await repo.update(tenant_id=1, id=uuid4(), payload={})
    with pytest.raises(NotImplementedError, match="immutable"):
        await repo.delete(tenant_id=1, id=uuid4())
    with pytest.raises(NotImplementedError, match="statement_for_update"):
        repo.statement_for_update(tenant_id=1, id=uuid4(), payload={})
    with pytest.raises(NotImplementedError, match="statement_for_delete"):
        repo.statement_for_delete(tenant_id=1, id=uuid4())


@pytest.mark.asyncio
async def test_create_artifact_rejects_content_hash_mismatch() -> None:
    repo = ArtifactRepository(_DummySession())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="content_hash mismatch"):
        await repo.create_artifact(
            tenant_id=1,
            run_id=TENANT_ONE_RUN_A_ID,
            project_id=uuid4(),
            kind="plan",
            content_hash="0" * 64,
            content_jsonb={"summary": "redacted"},
            payload_data_class="internal",
        )


def test_payload_data_class_enum_matches_migration_check_constraint() -> None:
    assert tuple(get_args(PayloadDataClass)) == ALL_PAYLOAD_DATA_CLASSES
    assert ALL_PAYLOAD_DATA_CLASSES == ("public", "internal", "confidential", "pii")
    assert (
        _check_constraint_values_from_migration("artifacts_ck_payload_data_class")
        == set(ALL_PAYLOAD_DATA_CLASSES)
    )


def test_migration_and_repository_prohibited_keys_match() -> None:
    migration = _ARTIFACTS_MIGRATION.read_text(encoding="utf-8")
    match = re.search(
        r"_PROHIBITED_PAYLOAD_KEYS:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\((.+?)\)",
        migration,
        re.DOTALL,
    )
    assert match, "migration _PROHIBITED_PAYLOAD_KEYS was not found"
    migration_keys = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert migration_keys == _PROHIBITED_PAYLOAD_KEYS
    assert _PROHIBITED_PAYLOAD_KEYS == _EXPECTED_PROHIBITED_PAYLOAD_KEYS
    assert len(_PROHIBITED_PAYLOAD_KEYS) == 21
    # R3-F-001 (R4): R2 で共通 _payload_secret_scan に統合され 8 pattern に拡張された
    # (sk-ant-... + PEM private key 追加)。drift detection のため exact name で確認する。
    assert len(_RAW_SECRET_PATTERNS) == 8
    expected_pattern_kinds = {
        "openai_api_key",
        "anthropic_api_key",
        "github_installation_token",
        "github_oauth_token",
        "github_personal_token",
        "tailscale_auth_key",
        "age_private_key",
        "pem_private_key",
    }
    actual_pattern_kinds = {kind for kind, _ in _RAW_SECRET_PATTERNS}
    assert actual_pattern_kinds == expected_pattern_kinds, (
        f"_RAW_SECRET_PATTERNS drift: expected {sorted(expected_pattern_kinds)}, "
        f"got {sorted(actual_pattern_kinds)}"
    )


@pytest.mark.asyncio
async def test_db_rejects_unknown_payload_data_class(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_artifact(session, payload_data_class="restricted")
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="artifacts_ck_payload_data_class",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_provider_continuation_ref_artifact_is_exportable_false(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)

        artifact_id = await _insert_artifact(
            session,
            kind="provider_continuation_ref",
            content_jsonb={"provider": "openai", "artifact_ref": "artifact://opaque"},
            payload_data_class="confidential",
            exportable=False,
        )
        await session.commit()

        exportable = await session.scalar(
            text("select exportable from artifacts where tenant_id = 1 and id = :artifact_id"),
            {"artifact_id": artifact_id},
        )
        assert exportable is False


@pytest.mark.asyncio
async def test_db_rejects_prohibited_payload_key_recursive(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_artifact(
                session,
                content_jsonb={"nested": {"provider_key": "redacted"}},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="artifacts_ck_no_prohibited_payload_keys",
        )
        await session.rollback()


def test_artifact_contract_rejects_raw_secret_keys_and_patterns_recursively() -> None:
    for prohibited_key in sorted(_PROHIBITED_PAYLOAD_KEYS):
        with pytest.raises(ValueError, match="prohibited payload key"):
            ArtifactRepository._assert_artifact_contract(
                kind="plan",
                content_hash=calculate_content_hash({"nested": {prohibited_key: "redacted"}}),
                content_jsonb={"nested": {prohibited_key: "redacted"}},
                payload_data_class="internal",
                exportable=True,
            )

    pattern_value = "ghs_" + ("a" * 24)
    content = {"context": [{"value": pattern_value}]}
    with pytest.raises(ValueError, match="raw secret pattern"):
        ArtifactRepository._assert_artifact_contract(
            kind="plan",
            content_hash=calculate_content_hash(content),
            content_jsonb=content,
            payload_data_class="internal",
            exportable=True,
        )


@pytest.mark.asyncio
async def test_parent_artifact_cross_run_and_cross_tenant_are_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await _insert_artifact(
            session,
            artifact_id=PARENT_ARTIFACT_ID,
            tenant_id=1,
            run_id=TENANT_ONE_RUN_A_ID,
        )
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_artifact(
                session,
                tenant_id=1,
                run_id=TENANT_ONE_RUN_B_ID,
                parent_artifact_id=PARENT_ARTIFACT_ID,
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="artifacts_parent_artifact_fkey",
        )
        await session.rollback()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_artifact(
                session,
                tenant_id=2,
                run_id=TENANT_TWO_RUN_ID,
                parent_artifact_id=PARENT_ARTIFACT_ID,
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="artifacts_parent_artifact_fkey",
        )
        await session.rollback()
