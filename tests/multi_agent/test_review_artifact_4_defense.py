"""SP-014 batch 0b: review_artifacts four-layer defense contract tests."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.db.session import create_engine
from backend.app.schemas.review_artifact import ReviewArtifactCreate
from backend.app.services.orchestrator.review_artifact_guard import (
    ReviewArtifactValidationError,
    validate_review_artifact_for_action_class,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000026001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000026002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000026003")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000026004")
PARENT_RUN_ID = UUID("00000000-0000-4000-8000-000000026010")
REQUESTER_RUN_ID = UUID("00000000-0000-4000-8000-000000026011")
REVIEWER_RUN_ID = UUID("00000000-0000-4000-8000-000000026012")
OTHER_REQUESTER_RUN_ID = UUID("00000000-0000-4000-8000-000000026013")
TARGET_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000026020")
REVIEW_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000026021")
OTHER_TARGET_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000026022")
POLICY_VERSION = "policy-pack-v1"
PROVIDER_FINGERPRINT_HASH = "1" * 64


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret="test-cookie-secret-review-artifact",
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
            raise AssertionError("review artifact tests require PostgreSQL.") from exc
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


def _json_hash(payload: dict[str, object]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(body).hexdigest()


def _target_payload(
    *,
    action_class: str = "task_write",
    policy_version: str = POLICY_VERSION,
    provider_request_fingerprint_hash: str = PROVIDER_FINGERPRINT_HASH,
) -> dict[str, object]:
    return {
        "summary": "review target patch",
        "policy_input": {
            "action_class": action_class,
            "policy_version": policy_version,
            "provider_request_fingerprint_hash": provider_request_fingerprint_hash,
        },
    }


TARGET_ARTIFACT_HASH = _json_hash(_target_payload())


async def _reset_tables(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            truncate
              review_artifacts,
              artifacts,
              agent_run_events,
              agent_runs,
              project_agent_roles,
              projects,
              workspaces,
              actors,
              tenants
            restart identity cascade
            """
        )
    )


async def _insert_fixture(session: AsyncSession) -> None:
    await _reset_tables(session)
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
            values (:actor_id, 1, 'human', 'human:review-artifact-test',
                    'Review Artifact Test Actor', '{"rls_ready": true}'::jsonb)
            """
        ),
        {"actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into workspaces (id, tenant_id, slug, name, owner_actor_id, metadata)
            values (:workspace_id, 1, 'review-artifact-workspace',
                    'review-artifact-workspace', :actor_id, '{"rls_ready": true}'::jsonb)
            """
        ),
        {"workspace_id": WORKSPACE_ID, "actor_id": ACTOR_ID},
    )
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values
              (:project_id, 1, :workspace_id, 'review-artifact-project',
               'review-artifact-project', 'active', '{"rls_ready": true}'::jsonb),
              (:other_project_id, 1, :workspace_id, 'review-artifact-other-project',
               'review-artifact-other-project', 'active', '{"rls_ready": true}'::jsonb)
            """
        ),
        {
            "project_id": PROJECT_ID,
            "other_project_id": OTHER_PROJECT_ID,
            "workspace_id": WORKSPACE_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into agent_runs (id, tenant_id, project_id, status, role_id, role_scope)
            values (:parent_run_id, 1, :project_id, 'running', 'orchestrator', 'global')
            """
        ),
        {"parent_run_id": PARENT_RUN_ID, "project_id": PROJECT_ID},
    )
    await session.execute(
        text(
            """
            insert into agent_runs (
              id, tenant_id, project_id, parent_run_id, status, role_id, role_scope
            )
            values
              (:requester_run_id, 1, :project_id, :parent_run_id,
               'diff_ready', 'implementer', 'global'),
              (:reviewer_run_id, 1, :project_id, :parent_run_id,
               'completed', 'reviewer', 'global'),
              (:other_requester_run_id, 1, :other_project_id, null,
               'diff_ready', 'implementer', 'global')
            """
        ),
        {
            "requester_run_id": REQUESTER_RUN_ID,
            "reviewer_run_id": REVIEWER_RUN_ID,
            "other_requester_run_id": OTHER_REQUESTER_RUN_ID,
            "parent_run_id": PARENT_RUN_ID,
            "project_id": PROJECT_ID,
            "other_project_id": OTHER_PROJECT_ID,
        },
    )
    await _insert_artifact(
        session,
        artifact_id=TARGET_ARTIFACT_ID,
        run_id=REQUESTER_RUN_ID,
        project_id=PROJECT_ID,
        kind="patch",
        payload=_target_payload(),
        content_hash=TARGET_ARTIFACT_HASH,
        trust_level="validated_artifact",
    )
    await _insert_artifact(
        session,
        artifact_id=REVIEW_ARTIFACT_ID,
        run_id=REVIEWER_RUN_ID,
        project_id=PROJECT_ID,
        kind="evidence",
        payload={"verdict": "pass", "findings": []},
        trust_level="validated_artifact",
    )
    other_payload = _target_payload(action_class="repo_write")
    await _insert_artifact(
        session,
        artifact_id=OTHER_TARGET_ARTIFACT_ID,
        run_id=OTHER_REQUESTER_RUN_ID,
        project_id=OTHER_PROJECT_ID,
        kind="patch",
        payload=other_payload,
        content_hash=_json_hash(other_payload),
        trust_level="validated_artifact",
    )


async def _insert_artifact(
    session: AsyncSession,
    *,
    artifact_id: UUID,
    run_id: UUID,
    project_id: UUID,
    kind: str,
    payload: dict[str, object],
    trust_level: str,
    content_hash: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            insert into artifacts (
              id, tenant_id, run_id, project_id, kind, content_hash, content_jsonb,
              payload_data_class, trust_level, exportable
            )
            values (
              :artifact_id, 1, :run_id, :project_id, :kind, :content_hash,
              cast(:content_jsonb as jsonb), 'internal', :trust_level, true
            )
            """
        ),
        {
            "artifact_id": artifact_id,
            "run_id": run_id,
            "project_id": project_id,
            "kind": kind,
            "content_hash": content_hash or _json_hash(payload),
            "content_jsonb": json.dumps(payload),
            "trust_level": trust_level,
        },
    )


def _candidate(**overrides: object) -> ReviewArtifactCreate:
    values: dict[str, object] = {
        "parent_run_id": PARENT_RUN_ID,
        "requester_run_id": REQUESTER_RUN_ID,
        "reviewer_run_id": REVIEWER_RUN_ID,
        "review_target_artifact_id": TARGET_ARTIFACT_ID,
        "review_artifact_id": REVIEW_ARTIFACT_ID,
        "action_class": "task_write",
        "target_artifact_hash": TARGET_ARTIFACT_HASH,
        "policy_version": POLICY_VERSION,
        "provider_request_fingerprint_hash": PROVIDER_FINGERPRINT_HASH,
        "review_verdict": "pass",
        "findings_count": 0,
    }
    values.update(overrides)
    return ReviewArtifactCreate.model_validate(values)


async def _insert_review_artifact_row(
    session: AsyncSession,
    candidate: ReviewArtifactCreate,
    *,
    action_class: str | None = None,
) -> UUID:
    review_artifact_row_id = uuid4()
    await session.execute(
        text(
            """
            insert into review_artifacts (
              id, tenant_id, project_id, parent_run_id, requester_run_id,
              reviewer_run_id, review_target_artifact_id, review_artifact_id,
              action_class, target_artifact_hash, policy_version,
              provider_request_fingerprint_hash, review_verdict, findings_count
            )
            values (
              :id, 1, :project_id, :parent_run_id, :requester_run_id,
              :reviewer_run_id, :review_target_artifact_id, :review_artifact_id,
              :action_class, :target_artifact_hash, :policy_version,
              :provider_request_fingerprint_hash, :review_verdict, :findings_count
            )
            """
        ),
        {
            "id": review_artifact_row_id,
            "project_id": PROJECT_ID,
            "parent_run_id": candidate.parent_run_id,
            "requester_run_id": candidate.requester_run_id,
            "reviewer_run_id": candidate.reviewer_run_id,
            "review_target_artifact_id": candidate.review_target_artifact_id,
            "review_artifact_id": candidate.review_artifact_id,
            "action_class": action_class or candidate.action_class,
            "target_artifact_hash": candidate.target_artifact_hash,
            "policy_version": candidate.policy_version,
            "provider_request_fingerprint_hash": candidate.provider_request_fingerprint_hash,
            "review_verdict": candidate.review_verdict,
            "findings_count": candidate.findings_count,
        },
    )
    return review_artifact_row_id


def test_pydantic_rejects_invalid_action_class_and_extra_field() -> None:
    with pytest.raises(ValidationError, match="action_class"):
        _candidate(action_class="merge")

    with pytest.raises(ValidationError, match="extra_forbidden|tenant_id"):
        ReviewArtifactCreate.model_validate(
            {
                "parent_run_id": PARENT_RUN_ID,
                "requester_run_id": REQUESTER_RUN_ID,
                "reviewer_run_id": REVIEWER_RUN_ID,
                "review_target_artifact_id": TARGET_ARTIFACT_ID,
                "review_artifact_id": REVIEW_ARTIFACT_ID,
                "action_class": "task_write",
                "target_artifact_hash": TARGET_ARTIFACT_HASH,
                "policy_version": POLICY_VERSION,
                "provider_request_fingerprint_hash": PROVIDER_FINGERPRINT_HASH,
                "review_verdict": "pass",
                "tenant_id": TENANT_ID,
            }
        )


@pytest.mark.asyncio
async def test_db_check_rejects_non_reviewable_action_class(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)

        with pytest.raises(SQLAlchemyError, match="review_artifacts_ck_action_class|action_class"):
            await _insert_review_artifact_row(session, _candidate(), action_class="merge")
            await session.commit()


@pytest.mark.asyncio
async def test_db_fk_rejects_cross_project_target_artifact(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)

        with pytest.raises(
            SQLAlchemyError,
            match="review_artifacts_target_artifact_fkey|review_target_artifact",
        ):
            await _insert_review_artifact_row(
                session,
                _candidate(
                    review_target_artifact_id=OTHER_TARGET_ARTIFACT_ID,
                    target_artifact_hash=_json_hash(_target_payload(action_class="repo_write")),
                    action_class="repo_write",
                ),
            )
            await session.commit()


@pytest.mark.asyncio
async def test_valid_candidate_passes_service_guard_and_db_insert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)

        candidate = _candidate()
        result = await validate_review_artifact_for_action_class(
            session,
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            candidate=candidate,
        )
        assert result.action_class == "task_write"
        assert result.target_artifact_hash == TARGET_ARTIFACT_HASH

        await _insert_review_artifact_row(session, candidate)
        await session.commit()


@pytest.mark.asyncio
async def test_service_guard_rejects_target_hash_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)

        with pytest.raises(ReviewArtifactValidationError, match="target_artifact_hash"):
            await validate_review_artifact_for_action_class(
                session,
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                candidate=_candidate(target_artifact_hash="f" * 64),
            )


@pytest.mark.asyncio
async def test_service_guard_rejects_action_class_policy_binding_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)

        with pytest.raises(ReviewArtifactValidationError, match="action_class"):
            await validate_review_artifact_for_action_class(
                session,
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                candidate=_candidate(action_class="repo_write"),
            )


@pytest.mark.asyncio
async def test_service_guard_uses_nested_policy_input_over_top_level_payload_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            payload = _target_payload()
            payload["action_class"] = "repo_write"
            target_hash = _json_hash(payload)
            await session.execute(
                text(
                    """
                    update artifacts
                       set content_jsonb = cast(:content_jsonb as jsonb),
                           content_hash = :target_hash
                     where tenant_id = 1
                       and id = :target_artifact_id
                    """
                ),
                {
                    "content_jsonb": json.dumps(payload),
                    "target_hash": target_hash,
                    "target_artifact_id": TARGET_ARTIFACT_ID,
                },
            )

        result = await validate_review_artifact_for_action_class(
            session,
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            candidate=_candidate(target_artifact_hash=target_hash),
        )

        assert result.action_class == "task_write"
        assert result.target_artifact_hash == target_hash


@pytest.mark.asyncio
async def test_service_guard_rejects_target_without_policy_input_binding(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            payload: dict[str, object] = {
                "summary": "review target patch",
                "action_class": "task_write",
                "policy_version": POLICY_VERSION,
                "provider_request_fingerprint_hash": PROVIDER_FINGERPRINT_HASH,
            }
            target_hash = _json_hash(payload)
            await session.execute(
                text(
                    """
                    update artifacts
                       set content_jsonb = cast(:content_jsonb as jsonb),
                           content_hash = :target_hash
                     where tenant_id = 1
                       and id = :target_artifact_id
                    """
                ),
                {
                    "content_jsonb": json.dumps(payload),
                    "target_hash": target_hash,
                    "target_artifact_id": TARGET_ARTIFACT_ID,
                },
            )

        with pytest.raises(ReviewArtifactValidationError, match="action_class"):
            await validate_review_artifact_for_action_class(
                session,
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                candidate=_candidate(target_artifact_hash=target_hash),
            )


@pytest.mark.asyncio
async def test_contract_rejects_non_reviewer_role(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            await session.execute(
                text(
                    """
                    update agent_runs
                       set role_id = 'implementer'
                     where tenant_id = 1
                       and project_id = :project_id
                       and id = :reviewer_run_id
                    """
                ),
                {"project_id": PROJECT_ID, "reviewer_run_id": REVIEWER_RUN_ID},
            )

        with pytest.raises(ReviewArtifactValidationError, match="role_id='reviewer'"):
            await validate_review_artifact_for_action_class(
                session,
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                candidate=_candidate(),
            )


@pytest.mark.asyncio
async def test_contract_rejects_requester_reviewer_identity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(ValidationError, match="reviewer_run_id"):
        _candidate(reviewer_run_id=REQUESTER_RUN_ID)

    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)

        direct_row = ReviewArtifactCreate.model_construct(
            parent_run_id=PARENT_RUN_ID,
            requester_run_id=REQUESTER_RUN_ID,
            reviewer_run_id=REQUESTER_RUN_ID,
            review_target_artifact_id=TARGET_ARTIFACT_ID,
            review_artifact_id=REVIEW_ARTIFACT_ID,
            action_class="task_write",
            target_artifact_hash=TARGET_ARTIFACT_HASH,
            policy_version=POLICY_VERSION,
            provider_request_fingerprint_hash=PROVIDER_FINGERPRINT_HASH,
            review_verdict="pass",
            findings_count=0,
        )
        with pytest.raises(
            SQLAlchemyError,
            match="review_artifacts_ck_reviewer_not_requester|reviewer",
        ):
            await _insert_review_artifact_row(session, direct_row)
            await session.commit()


@pytest.mark.asyncio
async def test_service_guard_rejects_constructed_requester_reviewer_identity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)

        direct_row = ReviewArtifactCreate.model_construct(
            parent_run_id=PARENT_RUN_ID,
            requester_run_id=REQUESTER_RUN_ID,
            reviewer_run_id=REQUESTER_RUN_ID,
            review_target_artifact_id=TARGET_ARTIFACT_ID,
            review_artifact_id=REVIEW_ARTIFACT_ID,
            action_class="task_write",
            target_artifact_hash=TARGET_ARTIFACT_HASH,
            policy_version=POLICY_VERSION,
            provider_request_fingerprint_hash=PROVIDER_FINGERPRINT_HASH,
            review_verdict="pass",
            findings_count=0,
        )
        with pytest.raises(ReviewArtifactValidationError, match="reviewer_run_id"):
            await validate_review_artifact_for_action_class(
                session,
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                candidate=direct_row,
            )


@pytest.mark.asyncio
async def test_service_guard_rejects_review_artifact_verdict_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            await session.execute(
                text(
                    """
                    update artifacts
                       set content_jsonb = '{"verdict":"fail","findings":[]}'::jsonb
                     where tenant_id = 1
                       and id = :review_artifact_id
                    """
                ),
                {"review_artifact_id": REVIEW_ARTIFACT_ID},
            )

        with pytest.raises(ReviewArtifactValidationError, match="review_verdict"):
            await validate_review_artifact_for_action_class(
                session,
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                candidate=_candidate(),
            )


@pytest.mark.asyncio
async def test_service_guard_rejects_review_artifact_findings_count_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)
            await session.execute(
                text(
                    """
                    update artifacts
                       set content_jsonb = '{"verdict":"pass","findings":[{"code":"F001"}]}'::jsonb
                     where tenant_id = 1
                       and id = :review_artifact_id
                    """
                ),
                {"review_artifact_id": REVIEW_ARTIFACT_ID},
            )

        with pytest.raises(ReviewArtifactValidationError, match="findings_count"):
            await validate_review_artifact_for_action_class(
                session,
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                candidate=_candidate(),
            )


@pytest.mark.asyncio
async def test_contract_rejects_cross_project_target_artifact(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await _insert_fixture(session)

        with pytest.raises(
            ReviewArtifactValidationError,
            match="review_target_artifact_id not found",
        ):
            await validate_review_artifact_for_action_class(
                session,
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                candidate=_candidate(
                    review_target_artifact_id=OTHER_TARGET_ARTIFACT_ID,
                    target_artifact_hash=_json_hash(_target_payload(action_class="repo_write")),
                    action_class="repo_write",
                ),
            )
