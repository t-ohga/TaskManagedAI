"""Sprint 12 batch 10: P0AcceptanceAudit writer skeleton tests."""

from __future__ import annotations

from uuid import UUID

from backend.app.db.models.audit_event import AuditEvent
from backend.app.services.audit.p0_acceptance_audit_writer import (
    P0AcceptanceAuditWriteContext,
    build_p0_acceptance_audit_event,
)
from backend.app.services.eval.p0_acceptance_audit_emit import (
    AUDIT_EVENT_TYPE_P0_ACCEPTANCE_REPORT_GENERATED,
    P0AcceptanceAuditPayload,
)

_EXPLICIT_ID = UUID("11111111-1111-4111-8111-111111111111")
_ACTOR_ID = UUID("22222222-2222-4222-8222-222222222222")


def _make_payload() -> P0AcceptanceAuditPayload:
    return P0AcceptanceAuditPayload(
        schema_version="1.0.0",
        timestamp="2026-05-18T00:00:00Z",
        p0_exit_decision=True,
        deficiency_count=0,
        deficiency_codes=(),
        final_chain_sha256="a" * 64,
        gated_rows_sha256="b" * 64,
        hard_gates_sha256="c" * 64,
        kpi_sha256="d" * 64,
        smoke_sha256="e" * 64,
        drill_entries_sha256="f" * 64,
        private_staging_sha256="0" * 64,
    )


def _make_context(
    *,
    actor_id: UUID = _ACTOR_ID,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    explicit_id: UUID | None = _EXPLICIT_ID,
) -> P0AcceptanceAuditWriteContext:
    return P0AcceptanceAuditWriteContext(
        tenant_id=1,
        actor_id=actor_id,
        correlation_id=correlation_id,
        trace_id=trace_id,
        explicit_id=explicit_id,
    )


def test_build_audit_event_fixes_event_type_constant() -> None:
    """event_type は AUDIT_EVENT_TYPE_P0_ACCEPTANCE_REPORT_GENERATED 固定."""
    audit_event = build_p0_acceptance_audit_event(
        payload=_make_payload(),
        context=_make_context(),
    )
    assert audit_event.event_type == AUDIT_EVENT_TYPE_P0_ACCEPTANCE_REPORT_GENERATED
    assert audit_event.event_type == "p0_acceptance_report_generated"


def test_build_audit_event_returns_orm_instance() -> None:
    """Build returns an `AuditEvent` ORM model instance."""
    audit_event = build_p0_acceptance_audit_event(
        payload=_make_payload(),
        context=_make_context(),
    )
    assert isinstance(audit_event, AuditEvent)


def test_build_audit_event_binds_caller_context_fields() -> None:
    """tenant_id / actor_id / correlation_id / trace_id は context から."""
    audit_event = build_p0_acceptance_audit_event(
        payload=_make_payload(),
        context=_make_context(
            correlation_id="corr-abc",
            trace_id="trace-xyz",
        ),
    )
    assert audit_event.tenant_id == 1
    assert audit_event.actor_id == _ACTOR_ID
    assert audit_event.correlation_id == "corr-abc"
    assert audit_event.trace_id == "trace-xyz"


def test_build_audit_event_principal_is_null_for_sign_off() -> None:
    """BL-0149 sign-off は principal_id=null (system emit、CHECK constraint 整合)."""
    audit_event = build_p0_acceptance_audit_event(
        payload=_make_payload(),
        context=_make_context(),
    )
    assert audit_event.principal_id is None


def test_build_audit_event_serializes_payload_to_dict() -> None:
    """event_payload は payload.to_dict() の結果と一致."""
    payload = _make_payload()
    audit_event = build_p0_acceptance_audit_event(
        payload=payload,
        context=_make_context(),
    )
    assert audit_event.event_payload == payload.to_dict()
    # raw secret 排除 invariant: deficiency_codes は list、final hash は 64-hex.
    assert audit_event.event_payload["final_chain_sha256"] == "a" * 64
    assert audit_event.event_payload["deficiency_codes"] == []


def test_build_audit_event_uses_explicit_id_when_provided() -> None:
    """test fixture 用 explicit_id が ORM id にそのまま反映."""
    audit_event = build_p0_acceptance_audit_event(
        payload=_make_payload(),
        context=_make_context(explicit_id=_EXPLICIT_ID),
    )
    assert audit_event.id == _EXPLICIT_ID


def test_build_audit_event_generates_uuid_when_explicit_id_is_none() -> None:
    """explicit_id=None なら uuid4 で生成、UUID4 (variant=8, version=4)."""
    audit_event = build_p0_acceptance_audit_event(
        payload=_make_payload(),
        context=_make_context(explicit_id=None),
    )
    assert isinstance(audit_event.id, UUID)
    assert audit_event.id.version == 4


def test_build_audit_event_no_raw_secret_in_payload_after_redaction() -> None:
    """deficiency_codes redaction を経た payload に raw secret pattern が無い."""
    payload = P0AcceptanceAuditPayload(
        schema_version="1.0.0",
        timestamp="2026-05-18T00:00:00Z",
        p0_exit_decision=False,
        deficiency_count=2,
        # build_p0_acceptance_audit_payload で抽出済の code symbol のみ
        deficiency_codes=("hard_gates_failed", "kpis_failed"),
        final_chain_sha256="0" * 64,
        gated_rows_sha256="0" * 64,
        hard_gates_sha256="0" * 64,
        kpi_sha256="0" * 64,
        smoke_sha256="0" * 64,
        drill_entries_sha256="0" * 64,
        private_staging_sha256="0" * 64,
    )
    audit_event = build_p0_acceptance_audit_event(
        payload=payload,
        context=_make_context(),
    )
    # raw secret pattern (sk- / ghp_ / AGE-SECRET- 等) が含まれないこと.
    serialized = repr(audit_event.event_payload)
    for forbidden in ("sk-", "ghp_", "AGE-SECRET-", "tskey-", "xoxb-"):
        assert forbidden not in serialized, (
            f"forbidden raw secret pattern in audit payload: {forbidden}"
        )
