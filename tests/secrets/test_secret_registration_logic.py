"""SecretRegistrationService の reject guard 群 (no-DB、session 到達前に発火)。

DB 統合 (crash-window / false-present e2e / cross-tenant material identity) は S4 (batch-3) の
DB-gated suite が担当する。本 test は session 非依存の入力検証 guard のみを mock で固める。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.app.services.secrets.secret_registration import (
    SecretRegistrationConflict,
    SecretRegistrationError,
    SecretRegistrationService,
)

_OWNER = uuid4()


def _service() -> SecretRegistrationService:
    # reject guard は _ensure_tenant_context (session 利用) より前に発火するため session/store は未使用。
    return SecretRegistrationService(session=MagicMock(), store=MagicMock())


def _rotate_service_with_old(
    *,
    secret_uri: str = "secret://local/project/openai#v1",  # noqa: S107 - URI、password ではない
    status: str = "active",
    material_state: str = "present",
) -> SecretRegistrationService:
    """rotate precondition gate を no-DB で検証する service。

    gate は ``_fetch`` (session 利用) の後に発火するため、``_ensure_tenant_context`` と ``_fetch`` を
    AsyncMock で置換し old の状態だけを制御する。gate が反応すれば create_metadata / store.store /
    commit に一切到達しない (write 前 reject を保証)。
    """
    service = SecretRegistrationService(session=MagicMock(), store=MagicMock())
    service._ensure_tenant_context = AsyncMock()  # type: ignore[method-assign]
    old = SimpleNamespace(
        secret_uri=secret_uri,
        status=status,
        material_state=material_state,
        scope="project",
        name="openai",
    )
    service._fetch = AsyncMock(return_value=old)  # type: ignore[method-assign]
    return service


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


# ---- rotate precondition gate (Codex R7-F1、write 前 fail-closed) ----


async def _call_rotate(service: SecretRegistrationService) -> None:
    await service.rotate(
        tenant_id=1,
        old_secret_ref_id=uuid4(),
        new_version="v2",
        owner_actor_id=_OWNER,
        raw_material=b"x",
        allowed_consumers=["api:provider_adapter"],
        allowed_operations=["provider.call"],
    )


async def test_rotate_rejects_non_local_old() -> None:
    service = _rotate_service_with_old(secret_uri="secret://sops/project/openai#v1")
    with pytest.raises(SecretRegistrationError):
        await _call_rotate(service)
    # write 前 reject: store.store / session.commit に未到達。
    service.store.store.assert_not_called()
    service.session.commit.assert_not_called()


async def test_rotate_rejects_non_active_old() -> None:
    service = _rotate_service_with_old(status="deprecated")
    with pytest.raises(SecretRegistrationConflict):
        await _call_rotate(service)
    service.store.store.assert_not_called()
    service.session.commit.assert_not_called()


async def test_rotate_rejects_old_material_not_present() -> None:
    # active だが material_state が未検証 (writing) の old から rotate しない (false-present 防止)。
    service = _rotate_service_with_old(material_state="writing")
    with pytest.raises(SecretRegistrationConflict):
        await _call_rotate(service)
    service.store.store.assert_not_called()
    service.session.commit.assert_not_called()


async def test_rotate_rejects_empty_allowlists() -> None:
    service = _rotate_service_with_old()  # local active present
    with pytest.raises(SecretRegistrationError):
        await service.rotate(
            tenant_id=1,
            old_secret_ref_id=uuid4(),
            new_version="v2",
            owner_actor_id=_OWNER,
            raw_material=b"x",
            allowed_consumers=[],
            allowed_operations=["provider.call"],
        )
    service.store.store.assert_not_called()
    service.session.commit.assert_not_called()
