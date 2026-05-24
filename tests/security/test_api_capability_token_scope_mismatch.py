from __future__ import annotations

import os
from collections import Counter
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.api.dependencies.api_capability_token import OPERATION_TOKEN_HEADER
from backend.app.services.auth import ApiCapabilityTokenDenied, ApiCapabilityTokenService
from tests.cli.test_capability_token_lifecycle import (
    ACTOR_ID,
    AUTH_CONTEXT_HASH,
    PROJECT_ID,
    REQUEST_BINDING_HASH,
    TENANT_ID,
    WORKSPACE_ID,
    _insert_fixture,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)

PROJECT_ID_TWO = UUID("00000000-0000-4000-8000-000000016204")


async def _insert_second_project(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into projects (id, tenant_id, workspace_id, slug, name, status, metadata)
            values (
              :project_id, 1, :workspace_id, 'cli-token-project-two',
              'cli-token-project-two', 'active', '{"rls_ready": true}'::jsonb
            )
            """
        ),
        {"project_id": PROJECT_ID_TWO, "workspace_id": WORKSPACE_ID},
    )


@pytest.mark.asyncio
async def test_authorize_request_rejects_project_scope_mismatch_and_audits_ref_only(
    cli_capability_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with cli_capability_session_factory() as session:
        await _insert_fixture(session)
        await _insert_second_project(session)
        issued = await ApiCapabilityTokenService(session).issue(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            project_id=PROJECT_ID,
            device_id="macbook-pro-dev",
            allowed_actions=["task_write"],
            scope_constraint={"project_id": str(PROJECT_ID)},
            auth_method="keyring",
            auth_context_hash=AUTH_CONTEXT_HASH,
            request_binding_hash=REQUEST_BINDING_HASH,
            ttl_minutes=5,
        )

        with pytest.raises(ApiCapabilityTokenDenied) as denied:
            await ApiCapabilityTokenService(session).authorize_request(
                tenant_id=TENANT_ID,
                actor_id=ACTOR_ID,
                raw_operation_token=issued.raw_operation_token,
                required_action="task_write",
                project_id=PROJECT_ID_TWO,
            )
        await session.commit()

        token_row = (
            await session.execute(
                text(
                    """
                    select status, last_used_at
                      from api_capability_tokens
                     where tenant_id = :tenant_id and id = :token_id
                    """
                ),
                {"tenant_id": TENANT_ID, "token_id": issued.token.id},
            )
        ).mappings().one()
        audit_rows = (
            await session.execute(
                text("select event_type, event_payload from audit_events order by created_at, id")
            )
        ).mappings().all()

    assert denied.value.reason_code == "project_scope_mismatch"
    assert token_row["status"] == "issued"
    assert token_row["last_used_at"] is None
    assert Counter(row["event_type"] for row in audit_rows) == {
        "api_capability_token_issued": 1,
        "api_capability_token_scope_mismatch": 1,
    }
    scope_payload = next(
        dict(row["event_payload"])
        for row in audit_rows
        if row["event_type"] == "api_capability_token_scope_mismatch"
    )
    assert scope_payload["reason_code"] == "project_scope_mismatch"
    assert scope_payload["token_project_id"] == str(PROJECT_ID)
    assert scope_payload["requested_project_id"] == str(PROJECT_ID_TWO)
    assert scope_payload["redaction_status"] == "ref_only"
    assert issued.raw_operation_token not in repr(audit_rows)


@pytest.mark.asyncio
async def test_authorize_request_rejects_action_scope_mismatch_without_using_token(
    cli_capability_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with cli_capability_session_factory() as session:
        await _insert_fixture(session)
        issued = await ApiCapabilityTokenService(session).issue(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            project_id=PROJECT_ID,
            device_id="macbook-pro-dev",
            allowed_actions=["task_list"],
            scope_constraint={"project_id": str(PROJECT_ID)},
            auth_method="keyring",
            auth_context_hash=AUTH_CONTEXT_HASH,
            request_binding_hash=REQUEST_BINDING_HASH,
            ttl_minutes=5,
        )

        with pytest.raises(ApiCapabilityTokenDenied) as denied:
            await ApiCapabilityTokenService(session).authorize_request(
                tenant_id=TENANT_ID,
                actor_id=ACTOR_ID,
                raw_operation_token=issued.raw_operation_token,
                required_action="task_write",
                project_id=PROJECT_ID,
            )
        await session.commit()

        event_payload = await session.scalar(
            text(
                """
                select event_payload
                  from audit_events
                 where event_type = 'api_capability_token_scope_mismatch'
                """
            )
        )
        last_used_at = await session.scalar(
            text("select last_used_at from api_capability_tokens where id = :token_id"),
            {"token_id": issued.token.id},
        )

    assert denied.value.reason_code == "action_scope_mismatch"
    assert dict(event_payload)["required_action"] == "task_write"
    assert dict(event_payload)["allowed_actions"] == ["task_list"]
    assert last_used_at is None


@pytest.mark.asyncio
async def test_authorize_request_success_marks_last_used_without_extra_audit(
    cli_capability_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with cli_capability_session_factory() as session:
        await _insert_fixture(session)
        issued = await ApiCapabilityTokenService(session).issue(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            project_id=PROJECT_ID,
            device_id="macbook-pro-dev",
            allowed_actions=["task_write"],
            scope_constraint={"project_id": str(PROJECT_ID)},
            auth_method="keyring",
            auth_context_hash=AUTH_CONTEXT_HASH,
            request_binding_hash=REQUEST_BINDING_HASH,
            ttl_minutes=5,
        )

        authorized = await ApiCapabilityTokenService(session).authorize_request(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            raw_operation_token=issued.raw_operation_token,
            required_action="task_write",
            project_id=PROJECT_ID,
        )
        await session.commit()

        event_types = (
            await session.execute(text("select event_type from audit_events order by created_at, id"))
        ).scalars().all()
        last_used_at = await session.scalar(
            text("select last_used_at from api_capability_tokens where id = :token_id"),
            {"token_id": issued.token.id},
        )

    assert authorized.token.id == issued.token.id
    assert last_used_at is not None
    assert event_types == ["api_capability_token_issued"]


@pytest.mark.asyncio
async def test_ticket_create_api_call_with_project_scope_mismatch_denies_and_audits(
    cli_capability_session_factory: async_sessionmaker[AsyncSession],
    cli_capability_client: AsyncClient,
) -> None:
    async with cli_capability_session_factory() as session:
        await _insert_fixture(session)
        await _insert_second_project(session)
        issued = await ApiCapabilityTokenService(session).issue(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            project_id=PROJECT_ID,
            device_id="macbook-pro-dev",
            allowed_actions=["task_create"],
            scope_constraint={"project_id": str(PROJECT_ID)},
            auth_method="keyring",
            auth_context_hash=AUTH_CONTEXT_HASH,
            request_binding_hash=REQUEST_BINDING_HASH,
            ttl_minutes=5,
        )
        await session.commit()

    response = await cli_capability_client.post(
        f"/api/v1/projects/{PROJECT_ID_TWO}/tickets",
        headers={OPERATION_TOKEN_HEADER: issued.raw_operation_token},
        json={"slug": "wrong-project", "title": "Wrong project"},
    )

    async with cli_capability_session_factory() as session:
        ticket_count = await session.scalar(
            text("select count(*) from tickets where slug = 'wrong-project'")
        )
        token_row = (
            await session.execute(
                text(
                    """
                    select status, last_used_at
                      from api_capability_tokens
                     where tenant_id = :tenant_id and id = :token_id
                    """
                ),
                {"tenant_id": TENANT_ID, "token_id": issued.token.id},
            )
        ).mappings().one()
        audit_rows = (
            await session.execute(
                text("select event_type, event_payload from audit_events order by created_at, id")
            )
        ).mappings().all()

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error_code": "api_capability_token_denied",
        "reason_code": "project_scope_mismatch",
    }
    assert ticket_count == 0
    assert token_row["status"] == "issued"
    assert token_row["last_used_at"] is None
    assert Counter(row["event_type"] for row in audit_rows) == {
        "api_capability_token_issued": 1,
        "api_capability_token_scope_mismatch": 1,
    }
    assert issued.raw_operation_token not in repr(audit_rows)
