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
from backend.app.db.models.context_snapshot import CONTEXT_SNAPSHOT_REQUIRED_COLUMNS
from backend.app.db.session import create_engine
from backend.app.domain.agent_runtime.snapshot_kind import (
    ALL_SNAPSHOT_KINDS,
    SnapshotKind,
)
from backend.app.repositories.context_snapshot import ContextSnapshotRepository

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTEXT_SNAPSHOT_MIGRATION = (
    _REPO_ROOT / "migrations" / "versions" / "0009_artifacts_context_snapshots.py"
)

TENANT_ONE_ACTOR_ID = UUID("00000000-0000-4000-8000-000000008001")
TENANT_TWO_ACTOR_ID = UUID("00000000-0000-4000-8000-000000008002")
TENANT_ONE_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000008011")
TENANT_TWO_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000008012")
TENANT_ONE_PROJECT_ID = UUID("00000000-0000-4000-8000-000000008021")
TENANT_TWO_PROJECT_ID = UUID("00000000-0000-4000-8000-000000008022")
TENANT_ONE_RUN_ID = UUID("00000000-0000-4000-8000-000000008031")
TENANT_TWO_RUN_ID = UUID("00000000-0000-4000-8000-000000008032")

EXPECTED_CONTEXT_SNAPSHOT_REQUIRED_COLUMNS = (
    "prompt_pack_version",
    "prompt_pack_lock",
    "policy_version",
    "policy_pack_lock",
    "repo_state",
    "tool_manifest",
    "evidence_set_hash",
    "provider_continuation_ref",
    "provider_request_fingerprint",
    "snapshot_kind",
)

_CONTEXT_SNAPSHOT_NON_NULL_COLUMNS = (
    "prompt_pack_version",
    "prompt_pack_lock",
    "policy_version",
    "policy_pack_lock",
    "repo_state",
    "tool_manifest",
    "evidence_set_hash",
    "provider_request_fingerprint",
    "snapshot_kind",
)


class _DummySession:
    pass


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-for-context-snapshot-tests",
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
            raise AssertionError("ContextSnapshot tests require a reachable test database.") from exc
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
    module = ast.parse(_CONTEXT_SNAPSHOT_MIGRATION.read_text(encoding="utf-8"))

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
              (:tenant_one_actor_id, 1, 'human', 'human:snapshot-tenant-one',
                'Snapshot Tenant One Actor', '{"rls_ready": true}'::jsonb),
              (:tenant_two_actor_id, 2, 'human', 'human:snapshot-tenant-two',
                'Snapshot Tenant Two Actor', '{"rls_ready": true}'::jsonb)
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
              (:tenant_one_workspace_id, 1, 'snapshot-workspace-one',
                'snapshot-workspace-one', :tenant_one_actor_id,
                '{"rls_ready": true}'::jsonb),
              (:tenant_two_workspace_id, 2, 'snapshot-workspace-two',
                'snapshot-workspace-two', :tenant_two_actor_id,
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
                'snapshot-project-one', 'snapshot-project-one', 'active',
                '{"rls_ready": true}'::jsonb),
              (:tenant_two_project_id, 2, :tenant_two_workspace_id,
                'snapshot-project-two', 'snapshot-project-two', 'active',
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
              (:tenant_one_run_id, 1, :tenant_one_project_id, 'queued'),
              (:tenant_two_run_id, 2, :tenant_two_project_id, 'queued')
            """
        ),
        {
            "tenant_one_run_id": TENANT_ONE_RUN_ID,
            "tenant_two_run_id": TENANT_TWO_RUN_ID,
            "tenant_one_project_id": TENANT_ONE_PROJECT_ID,
            "tenant_two_project_id": TENANT_TWO_PROJECT_ID,
        },
    )


def _valid_snapshot_payload() -> dict[str, Any]:
    return {
        "prompt_pack_version": "prompt-pack-v1",
        "prompt_pack_lock": "a" * 64,
        "policy_version": "policy-v1",
        "policy_pack_lock": "b" * 64,
        "repo_state": {
            "commit_sha": "1" * 40,
            "branch": "main",
            "dirty": False,
            "diff_hash": "c" * 64,
        },
        "tool_manifest": {
            "registry_version": "tool-registry-v1",
            "allowlist_hash": "d" * 64,
        },
        "evidence_set_hash": "e" * 64,
        "provider_continuation_ref": None,
        "provider_request_fingerprint": {
            "model_resolved": "mock-model",
            "api_version": "2026-05-09",
            "sdk_version": "0.0.0-test",
            "temperature": 0,
            "safety_settings": {"mode": "strict"},
        },
        "snapshot_kind": "input",
    }


def _valid_provider_continuation_ref() -> dict[str, Any]:
    return {
        "provider": "openai",
        "kind": "encrypted_reasoning",
        "artifact_ref": "artifact://opaque",
        "sha256": "f" * 64,
        "expires_at": "2026-05-09T00:00:00Z",
        "exportable": False,
    }


def _json_param(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


async def _insert_context_snapshot(
    session: AsyncSession,
    *,
    tenant_id: int = 1,
    run_id: UUID = TENANT_ONE_RUN_ID,
    **overrides: Any,
) -> UUID:
    payload = _valid_snapshot_payload()
    payload.update(overrides)
    snapshot_id = uuid4()

    await session.execute(
        text(
            """
            insert into context_snapshots (
              id,
              tenant_id,
              run_id,
              prompt_pack_version,
              prompt_pack_lock,
              policy_version,
              policy_pack_lock,
              repo_state,
              tool_manifest,
              evidence_set_hash,
              provider_continuation_ref,
              provider_request_fingerprint,
              snapshot_kind
            )
            values (
              :snapshot_id,
              :tenant_id,
              :run_id,
              :prompt_pack_version,
              :prompt_pack_lock,
              :policy_version,
              :policy_pack_lock,
              cast(:repo_state as jsonb),
              cast(:tool_manifest as jsonb),
              :evidence_set_hash,
              cast(:provider_continuation_ref as jsonb),
              cast(:provider_request_fingerprint as jsonb),
              :snapshot_kind
            )
            """
        ),
        {
            "snapshot_id": snapshot_id,
            "tenant_id": tenant_id,
            "run_id": run_id,
            "prompt_pack_version": payload["prompt_pack_version"],
            "prompt_pack_lock": payload["prompt_pack_lock"],
            "policy_version": payload["policy_version"],
            "policy_pack_lock": payload["policy_pack_lock"],
            "repo_state": _json_param(payload["repo_state"]),
            "tool_manifest": _json_param(payload["tool_manifest"]),
            "evidence_set_hash": payload["evidence_set_hash"],
            "provider_continuation_ref": _json_param(payload["provider_continuation_ref"]),
            "provider_request_fingerprint": _json_param(
                payload["provider_request_fingerprint"]
            ),
            "snapshot_kind": payload["snapshot_kind"],
        },
    )
    return snapshot_id


def test_context_snapshot_required_columns_match_contract_order() -> None:
    assert CONTEXT_SNAPSHOT_REQUIRED_COLUMNS == EXPECTED_CONTEXT_SNAPSHOT_REQUIRED_COLUMNS


def test_snapshot_kind_literal_matches_expected_five_values() -> None:
    assert tuple(get_args(SnapshotKind)) == ALL_SNAPSHOT_KINDS
    assert ALL_SNAPSHOT_KINDS == ("input", "pre_tool", "post_tool", "resume", "final")
    assert (
        _check_constraint_values_from_migration("context_snapshots_ck_snapshot_kind")
        == set(ALL_SNAPSHOT_KINDS)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("column_name", _CONTEXT_SNAPSHOT_NON_NULL_COLUMNS)
async def test_context_snapshot_required_non_nullable_columns_reject_null(
    session_factory: async_sessionmaker[AsyncSession],
    column_name: str,
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError):
            await _insert_context_snapshot(session, **{column_name: None})
            await session.commit()

        await session.rollback()


@pytest.mark.asyncio
async def test_provider_continuation_ref_nullable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)

        snapshot_id = await _insert_context_snapshot(session, provider_continuation_ref=None)
        await session.commit()

        stored_ref = await session.scalar(
            text(
                """
                select provider_continuation_ref
                from context_snapshots
                where tenant_id = 1 and id = :snapshot_id
                """
            ),
            {"snapshot_id": snapshot_id},
        )
        assert stored_ref is None


@pytest.mark.asyncio
async def test_db_rejects_unknown_snapshot_kind(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_context_snapshot(session, snapshot_kind="checkpoint")
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="context_snapshots_ck_snapshot_kind",
        )
        await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("column_name", "constraint_name"),
    [
        ("prompt_pack_lock", "context_snapshots_ck_prompt_pack_lock_sha256_hex"),
        ("policy_pack_lock", "context_snapshots_ck_policy_pack_lock_sha256_hex"),
        ("evidence_set_hash", "context_snapshots_ck_evidence_set_hash_sha256_hex"),
    ],
)
async def test_db_rejects_invalid_sha256_hex_columns(
    session_factory: async_sessionmaker[AsyncSession],
    column_name: str,
    constraint_name: str,
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_context_snapshot(session, **{column_name: "not-a-sha256"})
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name=constraint_name,
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_provider_continuation_ref_exportable_true_is_rejected_by_db_check(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            ref = _valid_provider_continuation_ref()
            ref["exportable"] = True
            await _insert_context_snapshot(session, provider_continuation_ref=ref)
            await session.commit()

        # migration 0009 は exportable=false rule を 2 箇所で重複定義する:
        #   1. _ck_provider_continuation_ref_exportable_false (line 213-217、
        #      create_table 内、単独 check)
        #   2. _ck_continuation_ref_required (line 272-287、後追い、composite で
        #      provider/kind/artifact_ref/sha256/expires_at と共に exportable='false' も検査)
        # PostgreSQL は composite (_required) を先に評価して fire するため、actual
        # constraint name は _continuation_ref_required になる。重複は migration 0009 の
        # append-only 性質から修正不可、test expected を実 fire 側に揃える
        # (broad audit Codex task で確認済)。
        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="context_snapshots_ck_continuation_ref_required",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_context_snapshot_rejects_empty_repo_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """F-003 (R2): repo_state={} は DB CHECK で reject。"""

    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_context_snapshot(session, repo_state={})
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="context_snapshots_ck_repo_state_required",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_context_snapshot_rejects_empty_tool_manifest(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """F-003 (R2): tool_manifest={} は DB CHECK で reject。"""

    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_context_snapshot(session, tool_manifest={})
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="context_snapshots_ck_tool_manifest_required",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_context_snapshot_rejects_empty_provider_request_fingerprint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """F-003 (R2): provider_request_fingerprint={} は DB CHECK で reject。"""

    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_context_snapshot(session, provider_request_fingerprint={})
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="context_snapshots_ck_fingerprint_required",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_context_snapshot_rejects_continuation_ref_without_required_keys(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """F-003 (R2): required keys 不在の provider_continuation_ref を reject。"""

    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_context_snapshot(
                session,
                provider_continuation_ref={"exportable": "false"},
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="context_snapshots_ck_continuation_ref_required",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_context_snapshot_repository_rejects_raw_secret_recursively() -> None:
    repo = ContextSnapshotRepository(_DummySession())  # type: ignore[arg-type]
    payload = _valid_snapshot_payload()
    payload["provider_request_fingerprint"] = {
        "model_resolved": "mock-model",
        "api_version": "2026-05-09",
        "sdk_version": "0.0.0-test",
        "temperature": 0,
        "safety_settings": {"nested": {"provider_key": "redacted"}},
    }

    with pytest.raises(ValueError, match="prohibited key"):
        await repo.create_snapshot(
            tenant_id=1,
            run_id=TENANT_ONE_RUN_ID,
            **payload,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"expires_at": 123}, "expires_at"),
        ({"expires_at": "not-a-date"}, "ISO 8601"),
        ({"provider": ""}, "provider"),
        ({"artifact_ref": ""}, "artifact_ref"),
        ({"sha256": "short-hash"}, "sha256"),
    ],
)
async def test_context_snapshot_repository_rejects_invalid_provider_continuation_ref_fields(
    override: dict[str, Any],
    match: str,
) -> None:
    """F-004 (R2): provider_continuation_ref 各 field の型・非空・timestamp を検証。"""

    repo = ContextSnapshotRepository(_DummySession())  # type: ignore[arg-type]
    payload = _valid_snapshot_payload()
    ref = _valid_provider_continuation_ref()
    ref.update(override)
    payload["provider_continuation_ref"] = ref

    with pytest.raises(ValueError, match=match):
        await repo.create_snapshot(
            tenant_id=1,
            run_id=TENANT_ONE_RUN_ID,
            **payload,
        )


@pytest.mark.asyncio
async def test_db_rejects_prohibited_key_in_jsonb_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_context_snapshot(
                session,
                tool_manifest={
                    "registry_version": "tool-registry-v1",
                    "allowlist_hash": "d" * 64,
                    "nested": {"provider_key": "redacted"},
                },
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23514",
            constraint_name="context_snapshots_ck_no_prohibited_payload_keys",
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_context_snapshot_run_id_composite_fk_rejects_cross_tenant_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _setup_runtime_fixture(session)
        await session.commit()

        with pytest.raises(IntegrityError) as exc_info:
            await _insert_context_snapshot(
                session,
                tenant_id=1,
                run_id=TENANT_TWO_RUN_ID,
            )
            await session.commit()

        _assert_integrity_error(
            exc_info.value,
            sqlstate="23503",
            constraint_name="context_snapshots_run_fkey",
        )
        await session.rollback()

