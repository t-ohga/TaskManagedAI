from __future__ import annotations

import hashlib
import inspect
import json
import unicodedata
from dataclasses import fields
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.app.domain.agent_runtime.operation_context import (
    OperationContext,
    compute_fingerprint,
)
from backend.app.services.secrets.broker import (
    BrokerIssueDenied,
    BrokerIssueResult,
    SecretBroker,
)

TENANT_ID = 1
ACTOR_ID = UUID("00000000-0000-4000-8000-000000004601")
RUN_ID = UUID("00000000-0000-4000-8000-000000004602")
SECRET_REF_ID = UUID("00000000-0000-4000-8000-000000004603")
APPROVAL_ID = UUID("00000000-0000-4000-8000-000000004604")


class _ApprovalSession:
    def __init__(self, approval: object | None) -> None:
        self.approval = approval

    async def scalar(self, statement: object) -> object | None:
        return self.approval


def _ctx(**overrides: object) -> OperationContext:
    values = {
        "tenant_id": TENANT_ID,
        "actor_id": ACTOR_ID,
        "run_id": RUN_ID,
        "secret_ref_id": SECRET_REF_ID,
        "requested_operation": "provider.call",
        "target": {
            "provider": "openai",
            "api_or_feature": "responses",
            "model_resolved": "gpt-5.4",
        },
        "payload_hash": hashlib.sha256(b"payload").hexdigest(),
        "approval_id": None,
        "policy_version": "policy-v1",
        "provider_compliance_matrix_version": "pcm-v1",
    }
    values.update(overrides)
    return OperationContext(**values)  # type: ignore[arg-type]


def _approved(**overrides: object) -> SimpleNamespace:
    values = {
        "tenant_id": TENANT_ID,
        "status": "approved",
        "action_class": "repo_write",
        "resource_ref": "repo:owner/repo:main",
        "diff_hash": "a" * 64,
        "provider_request_fingerprint": None,
        # SP-029 (Codex R6 F-2): repo mutation approval は同一 run binding 必須。
        "run_id": RUN_ID,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_operation_context_fingerprint_is_nfc_jcs_sha256() -> None:
    ctx = _ctx(target={"provider": "openai", "api_or_feature": "résponses", "model_resolved": "gpt-5.4"})
    payload = {
        "actor_id": str(ctx.actor_id),
        "approval_id": None,
        "payload_hash": ctx.payload_hash,
        "policy_version": ctx.policy_version,
        "provider_compliance_matrix_version": ctx.provider_compliance_matrix_version,
        "requested_operation": ctx.requested_operation,
        "run_id": str(ctx.run_id),
        "secret_ref_id": str(ctx.secret_ref_id),
        "target": {
            "api_or_feature": unicodedata.normalize("NFC", "résponses"),
            "model_resolved": "gpt-5.4",
            "provider": "openai",
        },
        "tenant_id": ctx.tenant_id,
    }
    expected = hashlib.sha256(
        unicodedata.normalize(
            "NFC",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        ).encode("utf-8")
    ).hexdigest()

    assert compute_fingerprint(ctx) == expected


def test_same_operation_context_has_same_fingerprint() -> None:
    assert compute_fingerprint(_ctx()) == compute_fingerprint(_ctx())


def test_different_targets_have_different_fingerprints() -> None:
    left = compute_fingerprint(
        _ctx(target={"provider": "openai", "api_or_feature": "responses", "model_resolved": "gpt-5.4"})
    )
    right = compute_fingerprint(
        _ctx(
            target={
                "provider": "anthropic",
                "api_or_feature": "messages",
                "model_resolved": "claude-sonnet-4.5",
            }
        )
    )
    assert left != right


def test_broker_issue_signature_has_no_caller_supplied_fingerprint() -> None:
    params = inspect.signature(SecretBroker.issue_capability_token).parameters
    assert "fingerprint" not in params
    assert "expected_request_fingerprint" not in params
    assert "request_fingerprint" not in params


def test_broker_issue_result_does_not_expose_expected_request_fingerprint() -> None:
    result_fields = {field.name for field in fields(BrokerIssueResult)}
    assert result_fields == {"raw_token", "token_id", "secret_ref_id", "expires_at"}
    assert "expected_request_fingerprint" not in result_fields


@pytest.mark.parametrize("ttl", [timedelta(minutes=4, seconds=59), timedelta(minutes=30, seconds=1)])
@pytest.mark.asyncio
async def test_issue_rejects_ttl_outside_five_to_thirty_minutes(ttl: timedelta) -> None:
    broker = SecretBroker(session=object())  # type: ignore[arg-type]

    with pytest.raises(BrokerIssueDenied) as exc_info:
        await broker.issue_capability_token(
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            secret_ref_id=SECRET_REF_ID,
            requested_operation="provider.call",
            target={
                "provider": "openai",
                "api_or_feature": "responses",
                "model_resolved": "gpt-5.4",
            },
            payload={"messages": ["hello"]},
            policy_version="policy-v1",
            provider_compliance_matrix_version="pcm-v1",
            ttl=ttl,
        )

    assert exc_info.value.reason_code == "ttl_out_of_bounds"


def test_issue_type_error_for_caller_supplied_fingerprint() -> None:
    broker = SecretBroker(session=object())  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        broker.issue_capability_token(  # type: ignore[call-arg]
            tenant_id=TENANT_ID,
            actor_id=ACTOR_ID,
            run_id=RUN_ID,
            secret_ref_id=SECRET_REF_ID,
            requested_operation="provider.call",
            target={
                "provider": "openai",
                "api_or_feature": "responses",
                "model_resolved": "gpt-5.4",
            },
            payload={"messages": ["hello"]},
            policy_version="policy-v1",
            provider_compliance_matrix_version="pcm-v1",
            expected_request_fingerprint="0" * 64,
        )


@pytest.mark.parametrize("status", ["pending", "deprecated", "revoked"])
def test_non_active_secret_refs_are_denied_for_issue(status: str) -> None:
    broker = SecretBroker(session=object())  # type: ignore[arg-type]
    secret_ref = type(
        "SecretRefFixture",
        (),
        {
            "status": status,
            "allowed_operations": ["provider.call"],
            "allowed_consumers": [str(ACTOR_ID)],
        },
    )()

    with pytest.raises(BrokerIssueDenied) as exc_info:
        broker._validate_secret_ref_for_issue(  # noqa: SLF001
            secret_ref=secret_ref,
            actor_id=ACTOR_ID,
            requested_operation="provider.call",
        )

    assert exc_info.value.reason_code == "secret_ref_not_active"


def test_allowed_consumers_and_operations_are_required_for_issue() -> None:
    broker = SecretBroker(session=object())  # type: ignore[arg-type]
    secret_ref = type(
        "SecretRefFixture",
        (),
        {
            "status": "active",
            "material_state": "present",
            "allowed_operations": ["repo.push"],
            "allowed_consumers": [str(ACTOR_ID)],
        },
    )()

    with pytest.raises(BrokerIssueDenied) as exc_info:
        broker._validate_secret_ref_for_issue(  # noqa: SLF001
            secret_ref=secret_ref,
            actor_id=ACTOR_ID,
            requested_operation="provider.call",
        )

    assert exc_info.value.reason_code == "operation_mismatch"


@pytest.mark.parametrize(
    ("approval", "expected_reason"),
    [
        (None, "approval_not_found"),
        (_approved(status="pending"), "approval_not_approved"),
        (_approved(action_class="pr_open"), "approval_action_class_mismatch"),
        (_approved(diff_hash="b" * 64), "approval_diff_hash_mismatch"),
        (_approved(resource_ref="repo:owner/other:main"), "approval_target_mismatch"),
        (_approved(tenant_id=2), "approval_tenant_mismatch"),
        # SP-029 (Codex R6 F-2): repo mutation approval は同一 run binding 必須。
        (_approved(run_id=None), "approval_run_mismatch"),
        (
            _approved(run_id=UUID("00000000-0000-4000-8000-0000000046ff")),
            "approval_run_mismatch",
        ),
    ],
)
@pytest.mark.asyncio
async def test_issue_validates_approval_binding_for_repo_push(
    approval: object | None,
    expected_reason: str,
) -> None:
    broker = SecretBroker(session=_ApprovalSession(approval))  # type: ignore[arg-type]

    with pytest.raises(BrokerIssueDenied) as exc_info:
        await broker._validate_approval(  # noqa: SLF001
            tenant_id=TENANT_ID,
            approval_id=APPROVAL_ID,
            run_id=RUN_ID,
            requested_operation="repo.push",
            target={"repo_full_name": "owner/repo", "branch": "main", "commit_sha": "a" * 40},
            payload_hash="a" * 64,
        )

    assert exc_info.value.reason_code == expected_reason


@pytest.mark.asyncio
async def test_issue_accepts_approval_binding_for_repo_push() -> None:
    broker = SecretBroker(session=_ApprovalSession(_approved()))  # type: ignore[arg-type]

    await broker._validate_approval(  # noqa: SLF001
        tenant_id=TENANT_ID,
        approval_id=APPROVAL_ID,
        run_id=RUN_ID,
        requested_operation="repo.push",
        target={"repo_full_name": "owner/repo", "branch": "main", "commit_sha": "a" * 40},
        payload_hash="a" * 64,
    )


@pytest.mark.asyncio
async def test_issue_validates_provider_call_approval_binding_when_present() -> None:
    broker = SecretBroker(
        session=_ApprovalSession(
            _approved(
                action_class="provider_call",
                resource_ref="provider:openai:responses:gpt-5.4",
                diff_hash=None,
                provider_request_fingerprint="a" * 64,
            )
        )
    )  # type: ignore[arg-type]

    await broker._validate_approval(  # noqa: SLF001
        tenant_id=TENANT_ID,
        approval_id=APPROVAL_ID,
        run_id=RUN_ID,
        requested_operation="provider.call",
        target={
            "provider": "openai",
            "api_or_feature": "responses",
            "model_resolved": "gpt-5.4",
        },
        payload_hash="a" * 64,
    )


@pytest.mark.parametrize("event_payload", [{"capability_token": "raw"}, {"raw_secret": "raw"}])
def test_audit_payload_contract_for_issue_has_no_raw_values(event_payload: dict[str, str]) -> None:
    forbidden_keys = {"capability_token", "raw_secret", "secret_value", "private_key"}
    assert forbidden_keys.intersection(event_payload)

