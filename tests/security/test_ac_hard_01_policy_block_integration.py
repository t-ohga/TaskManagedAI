"""AC-HARD-01 (policy_block_recall) Hard Gate integration test.

R2 (R1-F001): evaluate fixtures at the Sprint 3 policy / approval boundary.
The repository currently exposes ApprovalDecisionService and PolicyRuleRepository,
but not a PolicyDecisionService.evaluate() API. This test therefore exercises the
Sprint 3 policy_rules authority source directly and verifies that task_write
without approval is blocked for reason_code='task_write_requires_approval'.

This intentionally does not route through the Sprint 5 ComplianceGate provider
call data-class boundary; a data-class denial would be a false positive for
AC-HARD-01.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
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
from backend.app.domain.policy.action_class import ActionClass
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.policy_rule import PolicyRuleRepository
from eval.security.policy_block.loader import (
    PublicFixture,
    discover_fixtures,
    load_manifest,
    load_public_regression_fixtures,
    load_redacted_fixtures,
)

_DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai_test"
)
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASE_PATH = _REPO_ROOT / "eval/security/policy_block"
_ACTOR_ID = UUID("00000000-0000-4000-8000-000000006202")


@dataclass(frozen=True)
class _PolicyDecisionInput:
    tenant_id: int
    fixture_id: str
    action_class: ActionClass
    approval_state: str
    fixture_policy_version: str


@dataclass(frozen=True)
class _PolicyDecision:
    decision: Literal["allow", "deny"]
    reason_code: str
    policy_rule_version: str
    audit_payload: dict[str, Any]


class _AuditEmitter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def append(
        self,
        *,
        tenant_id: int,
        event_type: str,
        payload: dict[str, Any],
        actor_id: UUID | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.events.append(
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "payload": payload,
                "actor_id": actor_id,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            }
        )


def _integration_settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url=os.environ.get("TASKMANAGEDAI_DATABASE_URL", _DEFAULT_DATABASE_URL),
        redis_url=os.environ.get("TASKMANAGEDAI_REDIS_URL", _DEFAULT_REDIS_URL),
        dev_login_cookie_secret=os.environ.get(
            "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
            "test-cookie-secret-for-ac-hard-01-policy-block-tests",
        ),
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
            raise AssertionError(
                "AC-HARD-01 policy integration tests require a reachable test database."
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
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        yield factory
    finally:
        await engine.dispose()


def _fixture_to_policy_input(fixture: PublicFixture) -> _PolicyDecisionInput:
    fixture_input = fixture.input
    action_class = fixture_input.get("action_class")
    if not isinstance(action_class, str) or not action_class:
        raise AssertionError(f"Fixture {fixture.fixture_id} missing input.action_class")

    approval_state = fixture_input.get("approval_state")
    if not isinstance(approval_state, str) or not approval_state:
        raise AssertionError(f"Fixture {fixture.fixture_id} missing input.approval_state")

    policy_version = fixture.metadata.get("policy_version")
    if not isinstance(policy_version, str) or not policy_version:
        target = fixture_input.get("target")
        if isinstance(target, dict) and isinstance(target.get("policy_version"), str):
            policy_version = target["policy_version"]
        else:
            policy_version = "unknown-fixture-policy-version"

    return _PolicyDecisionInput(
        tenant_id=1,
        fixture_id=fixture.fixture_id,
        action_class=cast(ActionClass, action_class),
        approval_state=approval_state,
        fixture_policy_version=policy_version,
    )


async def _evaluate_policy_rule_lookup(
    session: AsyncSession,
    policy_input: _PolicyDecisionInput,
    audit: _AuditEmitter,
) -> _PolicyDecision:
    """Evaluate the Sprint 3 policy_rules source for an AC-HARD-01 fixture.

    PolicyDecisionService.evaluate() is not present in this codebase snapshot.
    The fail-closed contract still lives in policy_rules: task_write has
    effect='require_approval' and rule_json.reason_code='task_write_requires_approval'.
    """

    repo = PolicyRuleRepository(session)
    rules = await repo.list_by_action_class(
        tenant_id=policy_input.tenant_id,
        action_class=policy_input.action_class,
    )
    if not rules:
        raise AssertionError(
            f"Fixture {policy_input.fixture_id}: no policy_rule for "
            f"action_class={policy_input.action_class!r}"
        )

    rule = rules[0]
    rule_json = getattr(rule, "rule_json")
    if not isinstance(rule_json, dict):
        raise AssertionError(
            f"Fixture {policy_input.fixture_id}: policy_rule.rule_json must be an object"
        )

    reason_code = rule_json.get("reason_code")
    if not isinstance(reason_code, str) or not reason_code:
        raise AssertionError(
            f"Fixture {policy_input.fixture_id}: policy_rule.rule_json.reason_code missing"
        )

    effect = str(rule.effect)
    if effect == "deny":
        decision: Literal["allow", "deny"] = "deny"
    elif effect == "require_approval" and policy_input.approval_state != "approved":
        decision = "deny"
    elif effect == "allow" or policy_input.approval_state == "approved":
        decision = "allow"
    else:
        decision = "deny"
        reason_code = "policy_matrix_default_deny"

    payload = {
        "event_taxonomy": "audit_event",
        "fixture_id": policy_input.fixture_id,
        "decision": decision,
        "reason_code": reason_code,
        "action_class": policy_input.action_class,
        "policy_effect": effect,
        "approval_state": policy_input.approval_state,
        "fixture_policy_version": policy_input.fixture_policy_version,
        "policy_rule_version": rule.policy_version,
        "policy_boundary": "policy_rule_lookup",
    }
    await audit.append(
        tenant_id=policy_input.tenant_id,
        event_type="policy_decision_created",
        payload=payload,
        actor_id=_ACTOR_ID,
        correlation_id=f"correlation-{policy_input.fixture_id}",
        trace_id=f"trace-{policy_input.fixture_id}",
    )

    return _PolicyDecision(
        decision=decision,
        reason_code=reason_code,
        policy_rule_version=str(rule.policy_version),
        audit_payload=payload,
    )


def test_policy_block_fixture_loader_discovers_all_splits() -> None:
    manifest = load_manifest(_BASE_PATH / "manifest.json")
    discovered = discover_fixtures(_BASE_PATH)

    assert manifest["gate_id"] == "AC-HARD-01"
    assert manifest["metric_key"] == "policy_block_recall"
    assert set(discovered) == {"public_regression", "private_holdout", "adversarial_new"}
    assert len(discovered["public_regression"]) == 1
    assert load_redacted_fixtures(_BASE_PATH, kind="private_holdout") == []
    assert load_redacted_fixtures(_BASE_PATH, kind="adversarial_new") == []


@pytest.mark.asyncio
async def test_ac_hard_01_public_fixtures_blocked_via_policy_rule_lookup(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """R1-F001 (R2): AC-HARD-01 fixtures are blocked at policy/approval boundary.

    Each public_regression fixture must:
    - produce decision='deny'
    - preserve fixture.expected_reason_code exactly
    - emit a policy_decision_created audit event
    - count toward policy_block_recall only when the expected policy reason matched
    """

    fixtures = load_public_regression_fixtures(_BASE_PATH)
    expected_block_fixtures = [fixture for fixture in fixtures if fixture.expected_block is True]
    assert len(expected_block_fixtures) > 0

    blocked = 0
    async with session_factory() as session:
        for fixture in expected_block_fixtures:
            assert fixture.expected_decision == "block"
            assert fixture.expected_reason_code == "task_write_requires_approval"

            policy_input = _fixture_to_policy_input(fixture)
            assert policy_input.action_class == "task_write"
            assert policy_input.approval_state != "approved"

            audit = _AuditEmitter()
            decision = await _evaluate_policy_rule_lookup(session, policy_input, audit)

            assert decision.decision == "deny", f"Fixture {fixture.fixture_id} should be denied"
            assert decision.reason_code == fixture.expected_reason_code, (
                f"Fixture {fixture.fixture_id}: expected reason_code "
                f"{fixture.expected_reason_code!r}, got {decision.reason_code!r}"
            )
            assert decision.policy_rule_version

            audit_events = [
                event for event in audit.events if event["event_type"] == "policy_decision_created"
            ]
            assert len(audit_events) == 1
            payload = audit_events[0]["payload"]
            assert payload["decision"] == "deny"
            assert payload["reason_code"] == fixture.expected_reason_code
            assert payload["action_class"] == "task_write"
            assert payload["policy_effect"] == "require_approval"
            assert payload["policy_boundary"] == "policy_rule_lookup"
            assert_no_raw_secret(payload, path="$ac_hard_01_policy_decision_created")

            blocked += 1

    assert blocked == len(expected_block_fixtures), (
        f"AC-HARD-01 policy_block_recall: {blocked}/{len(expected_block_fixtures)} blocked"
    )

