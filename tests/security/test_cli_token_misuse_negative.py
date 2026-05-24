from __future__ import annotations

import os
from collections import Counter

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.services.auth import ApiCapabilityTokenService
from backend.app.services.secrets.broker import BrokerRedeemDenied, SecretBroker
from tests.cli.test_capability_token_lifecycle import (
    ACTOR_ID,
    AUTH_CONTEXT_HASH,
    PROJECT_ID,
    REQUEST_BINDING_HASH,
    TENANT_ID,
    _insert_fixture,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKMANAGEDAI_RUN_DB_TESTS") != "1",
    reason="Requires TASKMANAGEDAI_RUN_DB_TESTS=1 + test PostgreSQL container.",
)


@pytest.mark.asyncio
async def test_api_capability_token_cannot_be_redeemed_as_secretbroker_token(
    cli_capability_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with cli_capability_session_factory() as session:
        await _insert_fixture(session)
        await session.execute(
            text("truncate secret_capability_tokens, secret_refs restart identity cascade")
        )
        issued = await ApiCapabilityTokenService(session).issue(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            project_id=PROJECT_ID,
            device_id="macbook-pro-dev",
            allowed_actions=["secret_resolve"],
            scope_constraint={"project_id": str(PROJECT_ID)},
            auth_method="keyring",
            auth_context_hash=AUTH_CONTEXT_HASH,
            request_binding_hash=REQUEST_BINDING_HASH,
            ttl_minutes=5,
        )
        await session.commit()

        result: object = await SecretBroker(session=session).redeem_capability_token(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=None,
            raw_token=issued.raw_operation_token,
            requested_operation="secret.verify",
            target={"secret_ref_id": str(PROJECT_ID), "version": "v1"},
            payload_hash="0" * 64,
            policy_version="policy-v1",
        )
        await session.commit()

        assert isinstance(result, BrokerRedeemDenied)
        audit_rows = (
            await session.execute(
                text("select event_type, event_payload from audit_events order by created_at, id")
            )
        ).mappings().all()
        secret_token_count = await session.scalar(
            text("select count(*) from secret_capability_tokens")
        )
        api_token_status = await session.scalar(
            text("select status from api_capability_tokens where id = :token_id"),
            {"token_id": issued.token.id},
        )

    assert result.reason_code == "not_found"
    assert secret_token_count == 0
    assert api_token_status == "issued"
    assert Counter(row["event_type"] for row in audit_rows) == {
        "api_capability_token_issued": 1,
        "secret_capability_denied": 1,
    }
    secret_denial_payload = next(
        dict(row["event_payload"])
        for row in audit_rows
        if row["event_type"] == "secret_capability_denied"
    )
    assert secret_denial_payload["reason_code"] == "not_found"
    assert issued.raw_operation_token not in repr(audit_rows)
