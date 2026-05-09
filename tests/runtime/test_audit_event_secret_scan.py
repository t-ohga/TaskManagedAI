from __future__ import annotations

from uuid import UUID

import pytest

from backend.app.repositories import audit_event as audit_event_module
from backend.app.repositories.audit_event import AuditEventRepository

ACTOR_ID = UUID("00000000-0000-4000-8000-000000004b01")


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def test_audit_event_append_scans_payload_before_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    calls: list[tuple[dict[str, object], str]] = []

    async def ensure_tenant_context(self: AuditEventRepository, tenant_id: int) -> None:
        return None

    async def assert_principal_matches_actor(
        self: AuditEventRepository,
        *,
        tenant_id: int,
        actor_id: UUID | None,
        principal_id: UUID | None,
    ) -> None:
        return None

    def assert_no_raw_secret(payload: dict[str, object], *, path: str) -> None:
        calls.append((payload, path))

    monkeypatch.setattr(AuditEventRepository, "_ensure_tenant_context", ensure_tenant_context)
    monkeypatch.setattr(
        AuditEventRepository,
        "_assert_principal_matches_actor",
        assert_principal_matches_actor,
    )
    monkeypatch.setattr(audit_event_module, "assert_no_raw_secret", assert_no_raw_secret)

    payload = {"reason_code": "fingerprint_mismatch"}
    event = await AuditEventRepository(session).append(  # type: ignore[arg-type]
        tenant_id=1,
        event_type="secret_capability_denied",
        actor_id=ACTOR_ID,
        payload=payload,
    )

    assert calls == [(payload, "$audit_payload")]
    assert session.flushed is True
    assert event.event_payload == payload


@pytest.mark.asyncio
async def test_audit_event_append_rejects_raw_secret_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()

    async def ensure_tenant_context(self: AuditEventRepository, tenant_id: int) -> None:
        return None

    async def assert_principal_matches_actor(
        self: AuditEventRepository,
        *,
        tenant_id: int,
        actor_id: UUID | None,
        principal_id: UUID | None,
    ) -> None:
        return None

    monkeypatch.setattr(AuditEventRepository, "_ensure_tenant_context", ensure_tenant_context)
    monkeypatch.setattr(
        AuditEventRepository,
        "_assert_principal_matches_actor",
        assert_principal_matches_actor,
    )

    with pytest.raises(ValueError, match="prohibited key"):
        await AuditEventRepository(session).append(  # type: ignore[arg-type]
            tenant_id=1,
            event_type="secret_capability_denied",
            actor_id=ACTOR_ID,
            payload={"raw_secret": "redacted"},
        )

    assert session.added == []
    assert session.flushed is False



@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected_match",
    [
        # F-004 R3-F-002 (R4 Claude direct fix): nested prohibited keys
        ({"providers": {"openai": {"api_key": "redacted"}}}, "prohibited key"),
        ({"context": {"tokens": [{"capability_token": "redacted"}]}}, "prohibited key"),
        ({"meta": {"deeply": {"nested": {"provider_key": "redacted"}}}}, "prohibited key"),
        ({"audit": {"github_installation_token": "redacted"}}, "prohibited key"),
        # F-004 R3-F-002: raw secret patterns in scalar string values
        ({"summary": "leaked token sk-abcdefghijklmnopqrstuvwx"}, "raw secret pattern"),
        ({"summary": "key sk-ant-abcdefghijklmnopqrstuvwx"}, "raw secret pattern"),
        ({"context": {"value": "ghs_abcdefghijklmnopqrstuvwx"}}, "raw secret pattern"),
        (
            {"meta": "ca: -----BEGIN RSA PRIVATE KEY-----"},
            "raw secret pattern",
        ),
        (
            {"items": [{"label": "AGE-SECRET-KEY-1ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCDEFGHIJKLMNOP"}]},
            "raw secret pattern",
        ),
        # F-004 R3-F-002: prohibited key as dict key (recursive scan)
        ({"sk-abcdefghijklmnopqrstuvwx": {"value": "x"}}, "raw secret pattern"),
    ],
    ids=[
        "nested_api_key",
        "nested_capability_token",
        "deep_provider_key",
        "github_installation_token",
        "scalar_openai_pattern",
        "scalar_anthropic_pattern",
        "scalar_github_pattern",
        "scalar_pem_pattern",
        "scalar_age_pattern",
        "key_raw_token_pattern",
    ],
)
async def test_audit_event_append_rejects_nested_prohibited_payload(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
    expected_match: str,
) -> None:
    """R3-F-002 (R4): audit payload の nested prohibited keys / raw secret patterns を
    AuditEventRepository.append 経由で reject、session.add/flush が呼ばれない。"""
    session = _FakeSession()

    async def ensure_tenant_context(self: AuditEventRepository, tenant_id: int) -> None:
        return None

    async def assert_principal_matches_actor(
        self: AuditEventRepository,
        *,
        tenant_id: int,
        actor_id: UUID | None,
        principal_id: UUID | None,
    ) -> None:
        return None

    monkeypatch.setattr(AuditEventRepository, "_ensure_tenant_context", ensure_tenant_context)
    monkeypatch.setattr(
        AuditEventRepository,
        "_assert_principal_matches_actor",
        assert_principal_matches_actor,
    )

    with pytest.raises(ValueError, match=expected_match):
        await AuditEventRepository(session).append(  # type: ignore[arg-type]
            tenant_id=1,
            event_type="secret_capability_denied",
            actor_id=ACTOR_ID,
            payload=payload,
        )

    # F-004 R3-F-002: append が ValueError で session.add/flush が呼ばれない
    assert session.added == []
    assert session.flushed is False
