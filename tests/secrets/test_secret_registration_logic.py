"""SecretRegistrationService の reject guard 群 (no-DB、session 到達前に発火)。

DB 統合 (crash-window / false-present e2e / cross-tenant material identity) は S4 (batch-3) の
DB-gated suite が担当する。本 test は session 非依存の入力検証 guard のみを mock で固める。
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from backend.app.services.secrets.secret_registration import (
    SecretRegistrationError,
    SecretRegistrationService,
)

_OWNER = uuid4()


def _service() -> SecretRegistrationService:
    # reject guard は _ensure_tenant_context (session 利用) より前に発火するため session/store は未使用。
    return SecretRegistrationService(session=MagicMock(), store=MagicMock())


async def test_register_rejects_non_local_backend() -> None:
    with pytest.raises(SecretRegistrationError):
        await _service().register(
            tenant_id=1,
            scope="project",
            name="openai",
            version="v1",
            owner_actor_id=_OWNER,
            raw_material=b"x",
            allowed_consumers=["api:provider_adapter"],
            allowed_operations=["provider.call"],
            backend="sops",
        )


async def test_register_rejects_empty_allowlists() -> None:
    with pytest.raises(SecretRegistrationError):
        await _service().register(
            tenant_id=1,
            scope="project",
            name="openai",
            version="v1",
            owner_actor_id=_OWNER,
            raw_material=b"x",
            allowed_consumers=[],
            allowed_operations=["provider.call"],
        )


async def test_register_rejects_self_rotating_credential() -> None:
    with pytest.raises(SecretRegistrationError):
        await _service().register(
            tenant_id=1,
            scope="project",
            name="claude-oauth",
            version="v1",
            owner_actor_id=_OWNER,
            raw_material=b"x",
            allowed_consumers=["api:provider_adapter"],
            allowed_operations=["provider.call"],
            metadata={"self_rotating": True},
        )


async def test_register_rejects_host_ambient_supply_mode() -> None:
    with pytest.raises(SecretRegistrationError):
        await _service().register(
            tenant_id=1,
            scope="project",
            name="codex-oauth",
            version="v1",
            owner_actor_id=_OWNER,
            raw_material=b"x",
            allowed_consumers=["api:provider_adapter"],
            allowed_operations=["provider.call"],
            metadata={"credential_supply_mode": "host_ambient"},
        )


async def test_register_rejects_canary_in_metadata() -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - assert_no_raw_secret は ValueError
        await _service().register(
            tenant_id=1,
            scope="project",
            name="openai",
            version="v1",
            owner_actor_id=_OWNER,
            raw_material=b"x",
            allowed_consumers=["api:provider_adapter"],
            allowed_operations=["provider.call"],
            metadata={"api_key": "sk-canary-must-be-rejected-00000000"},
        )


def test_reject_self_rotating_static_guard() -> None:
    guard = SecretRegistrationService._reject_self_rotating
    # 正常 metadata は通る。
    guard(None)
    guard({"note": "ok"})
    # self-rotating / host-ambient は reject。
    with pytest.raises(SecretRegistrationError):
        guard({"self_rotating": True})
    with pytest.raises(SecretRegistrationError):
        guard({"credential_supply_mode": "host_ambient"})
