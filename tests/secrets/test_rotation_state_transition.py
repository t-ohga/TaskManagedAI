"""Sprint 11.5 batch 3b (BL-0138) rotation state transition tests.

DB integration 不要 (mock SecretRef + AsyncSession). raw secret pattern reject
+ status transitions + canary preflight 経路.

Verify items:
- 5 rotation operations enum (issue_new / promote / revoke / rollback / dry_run)
- canary preflight rejects sk-/ghp_/AGE-SECRET pattern in metadata
- promote: old:active→deprecated + new:pending→active
- rollback: current_active→deprecated + deprecated→active
- revoked は terminal、rollback path で revoked からの復元禁止
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from backend.app.services.secrets.rotation import (
    ROTATION_OPERATIONS,
    RotationDrillResult,
    RotationError,
    SecretRotationService,
    _canary_preflight,
    _validate_operation,
)

_TENANT_ID = 1


def _build_mock_session() -> tuple[MagicMock, AsyncMock]:
    """mock AsyncSession + scalar / execute mocks."""

    session = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=MagicMock())
    return session, session.scalar


def _mock_secret_ref(
    *,
    secret_ref_id: UUID,
    status: str,
    tenant_id: int = _TENANT_ID,
) -> MagicMock:
    ref = MagicMock()
    ref.id = secret_ref_id
    ref.status = status
    ref.tenant_id = tenant_id
    return ref


def _build_evaluator() -> tuple[SecretRotationService, MagicMock]:
    session, _scalar = _build_mock_session()
    svc = SecretRotationService(session)
    # tenant_context bypass for unit test
    svc._ensure_tenant_context = AsyncMock(return_value=None)  # noqa: SLF001
    return svc, session


def test_rotation_operations_enum_integrity() -> None:
    """5 rotation operations Literal + frozenset 整合."""

    assert ROTATION_OPERATIONS == frozenset(
        {"issue_new", "promote", "revoke", "rollback", "dry_run"}
    )


def test_validate_operation_accepts_valid() -> None:
    for op in ROTATION_OPERATIONS:
        assert _validate_operation(op) == op


def test_validate_operation_rejects_invalid() -> None:
    with pytest.raises(RotationError, match="invalid rotation operation"):
        _validate_operation("delete")


def test_canary_preflight_passes_clean_metadata() -> None:
    """clean metadata (raw secret pattern なし) は pass."""

    _canary_preflight({"scope": "project", "name": "openai", "ttl_hours": 168})


def test_canary_preflight_passes_empty_metadata() -> None:
    """empty/None metadata は no-op."""

    _canary_preflight(None)
    _canary_preflight({})


def test_canary_preflight_rejects_sk_pattern() -> None:
    """sk- pattern を含む metadata は reject."""

    with pytest.raises(RotationError, match="canary preflight"):
        _canary_preflight(
            {"leaked": "sk-fakeButLooksReal0123456789ABCDEF"}
        )


def test_canary_preflight_rejects_ghp_pattern() -> None:
    """ghp_ pattern も reject."""

    with pytest.raises(RotationError, match="canary preflight"):
        _canary_preflight({"leak": "ghp_FakeBut20PlusCharsABCDEFGHIJ"})


def test_canary_preflight_rejects_prohibited_key() -> None:
    """prohibited key (`api_key` 等) も reject."""

    with pytest.raises(RotationError, match="canary preflight"):
        _canary_preflight({"api_key": "anything"})


@pytest.mark.asyncio
async def test_issue_new_pending_passes() -> None:
    """新 secret_ref が pending status なら verify pass."""

    svc, session = _build_evaluator()
    new_id = uuid4()
    session.scalar = AsyncMock(
        return_value=_mock_secret_ref(secret_ref_id=new_id, status="pending")
    )

    result = await svc.issue_new(tenant_id=_TENANT_ID, new_secret_ref_id=new_id)
    assert result.success is True
    assert result.operation == "issue_new"
    assert "canary preflight passed" in result.plan_or_log
    assert result.transitions == ("new:pending (verified)",)


@pytest.mark.asyncio
async def test_issue_new_with_wrong_status_fails() -> None:
    """新 secret_ref が active 等 (pending でない) なら fail."""

    svc, session = _build_evaluator()
    new_id = uuid4()
    session.scalar = AsyncMock(
        return_value=_mock_secret_ref(secret_ref_id=new_id, status="active")
    )

    result = await svc.issue_new(tenant_id=_TENANT_ID, new_secret_ref_id=new_id)
    assert result.success is False
    assert result.error_message == "invalid_status"


@pytest.mark.asyncio
async def test_issue_new_with_canary_metadata_rejected() -> None:
    """metadata に canary pattern 含むと canary preflight reject."""

    svc, _session = _build_evaluator()
    new_id = uuid4()
    with pytest.raises(RotationError, match="canary preflight"):
        await svc.issue_new(
            tenant_id=_TENANT_ID,
            new_secret_ref_id=new_id,
            metadata={"leaked": "sk-fakeButLooksReal0123456789ABCDEF"},
        )


@pytest.mark.asyncio
async def test_promote_old_active_to_deprecated_and_new_to_active() -> None:
    """promote: old:active→deprecated + new:pending→active を 2 update call で実行."""

    svc, session = _build_evaluator()
    old_id = uuid4()
    new_id = uuid4()

    # session.scalar が 2 回 call される (old + new).
    session.scalar = AsyncMock(
        side_effect=[
            _mock_secret_ref(secret_ref_id=old_id, status="active"),
            _mock_secret_ref(secret_ref_id=new_id, status="pending"),
        ]
    )

    result = await svc.promote(
        tenant_id=_TENANT_ID, old_secret_ref_id=old_id, new_secret_ref_id=new_id
    )
    assert result.success is True
    assert result.operation == "promote"
    assert "old:active→deprecated" in result.transitions
    assert "new:pending→active" in result.transitions
    # execute が 2 回 (old update + new update) 呼ばれた
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_promote_old_not_active_fails() -> None:
    svc, session = _build_evaluator()
    old_id = uuid4()
    new_id = uuid4()
    session.scalar = AsyncMock(
        side_effect=[
            _mock_secret_ref(secret_ref_id=old_id, status="deprecated"),
            _mock_secret_ref(secret_ref_id=new_id, status="pending"),
        ]
    )

    result = await svc.promote(
        tenant_id=_TENANT_ID, old_secret_ref_id=old_id, new_secret_ref_id=new_id
    )
    assert result.success is False
    assert result.error_message == "invalid_old_status"


@pytest.mark.asyncio
async def test_promote_new_not_pending_fails() -> None:
    svc, session = _build_evaluator()
    old_id = uuid4()
    new_id = uuid4()
    session.scalar = AsyncMock(
        side_effect=[
            _mock_secret_ref(secret_ref_id=old_id, status="active"),
            _mock_secret_ref(secret_ref_id=new_id, status="active"),  # 既 active
        ]
    )

    result = await svc.promote(
        tenant_id=_TENANT_ID, old_secret_ref_id=old_id, new_secret_ref_id=new_id
    )
    assert result.success is False
    assert result.error_message == "invalid_new_status"


@pytest.mark.asyncio
async def test_revoke_deprecated_to_revoked() -> None:
    """revoke: deprecated→revoked 1 update call."""

    svc, session = _build_evaluator()
    ref_id = uuid4()
    session.scalar = AsyncMock(
        return_value=_mock_secret_ref(secret_ref_id=ref_id, status="deprecated")
    )

    result = await svc.revoke(tenant_id=_TENANT_ID, secret_ref_id=ref_id)
    assert result.success is True
    assert result.operation == "revoke"
    assert result.transitions == ("deprecated→revoked",)
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_revoke_active_status_fails() -> None:
    """revoke を active に対して呼ぶと fail (deprecated 経由必須)."""

    svc, session = _build_evaluator()
    ref_id = uuid4()
    session.scalar = AsyncMock(
        return_value=_mock_secret_ref(secret_ref_id=ref_id, status="active")
    )

    result = await svc.revoke(tenant_id=_TENANT_ID, secret_ref_id=ref_id)
    assert result.success is False
    assert result.error_message == "invalid_status"


@pytest.mark.asyncio
async def test_rollback_deprecated_to_active() -> None:
    """rollback: current_active→deprecated + deprecated→active."""

    svc, session = _build_evaluator()
    deprecated_id = uuid4()
    active_id = uuid4()
    session.scalar = AsyncMock(
        side_effect=[
            _mock_secret_ref(secret_ref_id=deprecated_id, status="deprecated"),
            _mock_secret_ref(secret_ref_id=active_id, status="active"),
        ]
    )

    result = await svc.rollback(
        tenant_id=_TENANT_ID,
        deprecated_secret_ref_id=deprecated_id,
        currently_active_secret_ref_id=active_id,
    )
    assert result.success is True
    assert "current_active→deprecated" in result.transitions
    assert "deprecated→active" in result.transitions
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_rollback_revoked_target_rejected() -> None:
    """revoked → active 復元は禁止 (revoked terminal)."""

    svc, session = _build_evaluator()
    revoked_id = uuid4()
    active_id = uuid4()
    session.scalar = AsyncMock(
        side_effect=[
            _mock_secret_ref(secret_ref_id=revoked_id, status="revoked"),
            _mock_secret_ref(secret_ref_id=active_id, status="active"),
        ]
    )

    result = await svc.rollback(
        tenant_id=_TENANT_ID,
        deprecated_secret_ref_id=revoked_id,
        currently_active_secret_ref_id=active_id,
    )
    assert result.success is False
    assert result.error_message == "invalid_rollback_target_status"


@pytest.mark.asyncio
async def test_dry_run_promote_plan() -> None:
    """dry_run mode: plan output、実 DB update なし."""

    svc, session = _build_evaluator()
    old_id = uuid4()
    new_id = uuid4()
    result = await svc.dry_run_plan(
        tenant_id=_TENANT_ID,
        operation="promote",
        old_secret_ref_id=old_id,
        new_secret_ref_id=new_id,
    )
    assert result.dry_run is True
    assert result.success is True
    assert "old:active→deprecated" in result.transitions
    assert "new:pending→active" in result.transitions
    # session.execute は dry-run で呼ばれない
    assert session.execute.await_count == 0


@pytest.mark.asyncio
async def test_dry_run_with_canary_metadata_rejected() -> None:
    """dry-run でも canary preflight が pattern 検出して reject."""

    svc, _session = _build_evaluator()
    with pytest.raises(RotationError, match="canary preflight"):
        await svc.dry_run_plan(
            tenant_id=_TENANT_ID,
            operation="issue_new",
            new_secret_ref_id=uuid4(),
            metadata={"leaked": "ghp_FakeBut20PlusCharsABCDEFGHIJ"},
        )


def test_rotation_drill_result_dataclass_fields() -> None:
    """RotationDrillResult が必須 field 持つ確認."""

    r = RotationDrillResult(
        timestamp=datetime.now(tz=UTC).isoformat(),
        operation="dry_run",
        dry_run=True,
        success=True,
        old_secret_ref_id=None,
        new_secret_ref_id=None,
        transitions=(),
        plan_or_log="test plan",
    )
    assert r.success is True
    assert r.error_message is None
