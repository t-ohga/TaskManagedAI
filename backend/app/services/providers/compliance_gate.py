from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.domain.agent_runtime.operation_context import compute_payload_hash
from backend.app.domain.artifact.data_class import PayloadDataClass
from backend.app.domain.provider.compliance import (
    PAYLOAD_DATA_CLASS_ORDINAL,
    ComplianceDecision,
    ComplianceDecisionKind,
    ComplianceMatrixEntry,
    ComplianceReasonCode,
    data_class_ordinal,
)
from backend.app.domain.provider.fingerprint import compute_provider_request_fingerprint
from backend.app.domain.provider.request import ProviderRequest
from backend.app.domain.provider.result import ProviderResult
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.services.agent_runtime.event_log import transition_with_event
from backend.app.services.providers.preflight import provider_request_preflight

MatrixMapping = Mapping[tuple[str, str], ComplianceMatrixEntry]
MatrixLoader = Callable[[], MatrixMapping] | MatrixMapping


class ComplianceGate:
    def __init__(
        self,
        matrix_loader: MatrixLoader,
        audit_emitter: object | None = None,
    ) -> None:
        self._matrix_loader = matrix_loader
        self._audit_emitter = audit_emitter

    def evaluate(self, request: ProviderRequest) -> ComplianceDecision:
        matrix = self._load_matrix()
        request_matrix_version = _request_matrix_version(request)
        matrix_version = _matrix_version(matrix, default=request_matrix_version)

        if request_matrix_version != matrix_version:
            return _decision(
                decision="deny",
                reason_code="provider_not_in_matrix",
                payload_data_class=_payload_class_or_none(
                    getattr(request, "payload_data_class", None)
                ),
                allowed_data_class=None,
                effective_allowed_data_class=None,
                matrix_version=matrix_version,
            )

        payload_data_class = getattr(request, "payload_data_class", None)
        if payload_data_class not in PAYLOAD_DATA_CLASS_ORDINAL:
            return _decision(
                decision="deny",
                reason_code="payload_data_class_unset",
                payload_data_class=None,
                allowed_data_class=None,
                effective_allowed_data_class=None,
                matrix_version=matrix_version,
            )

        payload_class = cast(PayloadDataClass, payload_data_class)
        entry = matrix.get((request.provider, request.api_or_feature))
        if entry is None:
            return _decision(
                decision="deny",
                reason_code="provider_not_in_matrix",
                payload_data_class=payload_class,
                allowed_data_class=None,
                effective_allowed_data_class=None,
                matrix_version=matrix_version,
            )

        allowed_data_class = entry.allowed_data_class
        if data_class_ordinal(payload_class) > data_class_ordinal(allowed_data_class):
            return _decision(
                decision="deny",
                reason_code="payload_data_class_exceeds_allowed",
                payload_data_class=payload_class,
                allowed_data_class=allowed_data_class,
                effective_allowed_data_class=allowed_data_class,
                matrix_version=matrix_version,
            )

        effective_allowed_data_class, downgrade_reason = _effective_allowed_data_class(entry)

        if entry.training_use != "no" and data_class_ordinal(payload_class) >= data_class_ordinal(
            "internal"
        ):
            return _decision(
                decision="deny",
                reason_code="training_use_not_no",
                payload_data_class=payload_class,
                allowed_data_class=allowed_data_class,
                effective_allowed_data_class=effective_allowed_data_class,
                matrix_version=matrix_version,
            )

        if entry.zdr_eligible in {"no", "n/a"} and data_class_ordinal(
            payload_class
        ) >= data_class_ordinal("internal"):
            return _decision(
                decision="deny",
                reason_code="zdr_ineligible",
                payload_data_class=payload_class,
                allowed_data_class=allowed_data_class,
                effective_allowed_data_class=effective_allowed_data_class,
                matrix_version=matrix_version,
            )

        if data_class_ordinal(payload_class) > data_class_ordinal(effective_allowed_data_class):
            return _decision(
                decision="deny",
                reason_code="effective_allowed_data_class_exceeded",
                payload_data_class=payload_class,
                allowed_data_class=allowed_data_class,
                effective_allowed_data_class=effective_allowed_data_class,
                matrix_version=matrix_version,
            )

        if (
            downgrade_reason is not None
            and data_class_ordinal(effective_allowed_data_class)
            < data_class_ordinal(allowed_data_class)
        ):
            return _decision(
                decision="downgrade",
                reason_code=downgrade_reason,
                payload_data_class=payload_class,
                allowed_data_class=allowed_data_class,
                effective_allowed_data_class=effective_allowed_data_class,
                matrix_version=matrix_version,
            )

        return _decision(
            decision="allow",
            reason_code="allow",
            payload_data_class=payload_class,
            allowed_data_class=allowed_data_class,
            effective_allowed_data_class=effective_allowed_data_class,
            matrix_version=matrix_version,
        )

    async def enforce(
        self,
        session: AsyncSession,
        *,
        run: AgentRun,
        request: ProviderRequest,
        actor_id: UUID,
    ) -> tuple[ComplianceDecision, ProviderResult | None]:
        """ComplianceGate enforce.

        AuditEvent taxonomy is separate from AgentRunEvent taxonomy:
        policy_decision_created/provider_blocked are AuditEvent event_type values,
        while the run-scoped transition always emits AgentRunEvent policy_blocked.
        """

        _assert_run_tenant_matches_request(run, request)

        decision = self.evaluate(request)

        if decision.decision == "deny":
            audit_event = await self._emit_audit_event(
                session,
                tenant_id=request.tenant_id,
                event_type="policy_decision_created",
                payload=_audit_payload(
                    event_type="policy_decision_created",
                    request=request,
                    run=run,
                    decision=decision,
                    audit_decision="deny",
                    actor_id=actor_id,
                ),
                actor_id=actor_id,
                run=run,
            )
            await _transition_policy_blocked(
                session=session,
                run=run,
                request=request,
                decision=decision,
                actor_id=actor_id,
                audit_event_type="policy_decision_created",
                audit_event_id=_audit_event_id(audit_event),
            )
            return decision, _blocked_provider_result(
                request=request,
                decision=decision,
                status="data_class_deny",
            )

        preflight = provider_request_preflight(request)
        if preflight.decision == "deny":
            blocked_decision = decision.model_copy(
                update={
                    "decision": "deny",
                    "reason_code": "provider_request_preflight_violation",
                }
            )
            await self._emit_audit_event(
                session,
                tenant_id=request.tenant_id,
                event_type="policy_decision_created",
                payload=_audit_payload(
                    event_type="policy_decision_created",
                    request=request,
                    run=run,
                    decision=blocked_decision,
                    audit_decision="deny",
                    actor_id=actor_id,
                    pattern_hit_kind=preflight.pattern_hit_kind,
                ),
                actor_id=actor_id,
                run=run,
            )
            provider_blocked_event = await self._emit_audit_event(
                session,
                tenant_id=request.tenant_id,
                event_type="provider_blocked",
                payload=_audit_payload(
                    event_type="provider_blocked",
                    request=request,
                    run=run,
                    decision=blocked_decision,
                    audit_decision="deny",
                    actor_id=actor_id,
                    pattern_hit_kind=preflight.pattern_hit_kind,
                ),
                actor_id=actor_id,
                run=run,
            )
            await _transition_policy_blocked(
                session=session,
                run=run,
                request=request,
                decision=blocked_decision,
                actor_id=actor_id,
                pattern_hit_kind=preflight.pattern_hit_kind,
                audit_event_type="provider_blocked",
                audit_event_id=_audit_event_id(provider_blocked_event),
            )
            return blocked_decision, _blocked_provider_result(
                request=request,
                decision=blocked_decision,
                status="preflight_deny",
                pattern_hit_kind=preflight.pattern_hit_kind,
            )

        await self._emit_audit_event(
            session,
            tenant_id=request.tenant_id,
            event_type="policy_decision_created",
            payload=_audit_payload(
                event_type="policy_decision_created",
                request=request,
                run=run,
                decision=decision,
                audit_decision="allow",
                actor_id=actor_id,
                pattern_hit_kind="none",
            ),
            actor_id=actor_id,
            run=run,
        )
        return decision, None

    def _load_matrix(self) -> MatrixMapping:
        loaded = self._matrix_loader() if callable(self._matrix_loader) else self._matrix_loader
        if not isinstance(loaded, Mapping):
            raise TypeError("matrix_loader must return a mapping.")
        return loaded

    async def _emit_audit_event(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        event_type: str,
        payload: dict[str, Any],
        actor_id: UUID,
        run: AgentRun,
    ) -> object:
        assert_no_raw_secret(payload, path="$provider_compliance_audit_payload")

        emitter = self._audit_emitter
        result: object
        if emitter is None:
            result = AuditEventRepository(session).append(
                tenant_id=tenant_id,
                event_type=event_type,
                payload=payload,
                actor_id=actor_id,
                correlation_id=_string_or_none(getattr(run, "correlation_id", None)),
                trace_id=_string_or_none(getattr(run, "trace_id", None)),
            )
            if inspect.isawaitable(result):
                result = await result
            return result

        append = getattr(emitter, "append", None)
        if callable(append):
            result = append(
                tenant_id=tenant_id,
                event_type=event_type,
                payload=payload,
                actor_id=actor_id,
                correlation_id=_string_or_none(getattr(run, "correlation_id", None)),
                trace_id=_string_or_none(getattr(run, "trace_id", None)),
            )
        elif callable(emitter):
            callback = cast(Callable[..., object], emitter)
            result = callback(
                session=session,
                tenant_id=tenant_id,
                event_type=event_type,
                payload=payload,
                actor_id=actor_id,
                correlation_id=_string_or_none(getattr(run, "correlation_id", None)),
                trace_id=_string_or_none(getattr(run, "trace_id", None)),
            )
        else:
            raise TypeError("audit_emitter must be None, callable, or expose append().")

        if inspect.isawaitable(result):
            result = await result
        return result


def _effective_allowed_data_class(
    entry: ComplianceMatrixEntry,
) -> tuple[PayloadDataClass, ComplianceReasonCode | None]:
    effective = entry.allowed_data_class
    reason: ComplianceReasonCode | None = None

    if entry.training_use != "no":
        return "public", "training_use_not_no"

    if entry.zdr_eligible in {"no", "n/a"}:
        downgraded = _min_data_class(effective, "public")
        return downgraded, "zdr_ineligible" if downgraded != entry.allowed_data_class else None

    if entry.zdr_eligible == "conditional" and entry.condition_status != "verified":
        effective, reason = _downgrade_to_internal(
            effective,
            current_reason=reason,
            new_reason="condition_unverified",
        )

    if entry.retention == "unverified" and data_class_ordinal(effective) >= data_class_ordinal(
        "confidential"
    ):
        effective, reason = _downgrade_to_internal(
            effective,
            current_reason=reason,
            new_reason="retention_unverified",
        )

    if (
        entry.region_or_data_transfer == "unverified"
        and data_class_ordinal(effective) >= data_class_ordinal("confidential")
    ):
        effective, reason = _downgrade_to_internal(
            effective,
            current_reason=reason,
            new_reason="region_unverified",
        )

    if entry.plan_required == "none" and data_class_ordinal(effective) >= data_class_ordinal(
        "confidential"
    ):
        effective, reason = _downgrade_to_internal(
            effective,
            current_reason=reason,
            new_reason="plan_unverified",
        )

    return effective, reason


def _downgrade_to_internal(
    value: PayloadDataClass,
    *,
    current_reason: ComplianceReasonCode | None,
    new_reason: ComplianceReasonCode,
) -> tuple[PayloadDataClass, ComplianceReasonCode]:
    downgraded = _min_data_class(value, "internal")
    return downgraded, current_reason or new_reason


def _decision(
    *,
    decision: ComplianceDecisionKind,
    reason_code: ComplianceReasonCode,
    payload_data_class: PayloadDataClass | None,
    allowed_data_class: PayloadDataClass | None,
    effective_allowed_data_class: PayloadDataClass | None,
    matrix_version: str,
) -> ComplianceDecision:
    return ComplianceDecision(
        decision=decision,
        reason_code=reason_code,
        payload_data_class=payload_data_class,
        allowed_data_class=allowed_data_class,
        effective_allowed_data_class=effective_allowed_data_class,
        provider_compliance_matrix_version=matrix_version,
    )


def _audit_payload(
    *,
    event_type: str,
    request: ProviderRequest,
    run: AgentRun,
    decision: ComplianceDecision,
    audit_decision: Literal["allow", "deny"],
    actor_id: UUID,
    pattern_hit_kind: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_type": event_type,
        "event_taxonomy": "audit_event",
        "decision": audit_decision,
        "compliance_decision": decision.decision,
        "reason_code": decision.reason_code,
        "provider": request.provider,
        "api_or_feature": request.api_or_feature,
        "payload_data_class": decision.payload_data_class,
        "allowed_data_class": decision.allowed_data_class,
        "effective_allowed_data_class": decision.effective_allowed_data_class,
        "provider_compliance_matrix_version": decision.provider_compliance_matrix_version,
        "request_provider_compliance_matrix_version": _request_matrix_version(request),
        "matrix_version_mismatch": _matrix_version_mismatch(request, decision),
        "policy_version": _string_or_default(getattr(run, "policy_version", None), "unknown"),
        "provider_request_fingerprint": _safe_provider_request_fingerprint(
            request,
            matrix_version=_request_matrix_version(request),
        ),
        "run_id": str(request.run_id),
        "actor_id": str(actor_id),
        "trace_id": _string_or_none(getattr(run, "trace_id", None)),
        "correlation_id": _string_or_none(getattr(run, "correlation_id", None)),
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "redacted": True,
    }
    if pattern_hit_kind is not None:
        payload["pattern_hit_kind"] = pattern_hit_kind
    assert_no_raw_secret(payload, path="$provider_compliance_audit_payload")
    return payload


async def _transition_policy_blocked(
    *,
    session: AsyncSession,
    run: AgentRun,
    request: ProviderRequest,
    decision: ComplianceDecision,
    actor_id: UUID,
    audit_event_type: str,
    audit_event_id: str | None,
    pattern_hit_kind: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "decision": "deny",
        "reason_code": decision.reason_code,
        "provider": request.provider,
        "api_or_feature": request.api_or_feature,
        "payload_data_class": decision.payload_data_class,
        "allowed_data_class": decision.allowed_data_class,
        "effective_allowed_data_class": decision.effective_allowed_data_class,
        "provider_compliance_matrix_version": decision.provider_compliance_matrix_version,
        "request_provider_compliance_matrix_version": _request_matrix_version(request),
        "matrix_version_mismatch": _matrix_version_mismatch(request, decision),
        "provider_request_fingerprint": _safe_provider_request_fingerprint(
            request,
            matrix_version=_request_matrix_version(request),
        ),
        "audit_event_type": audit_event_type,
        "redacted": True,
    }
    if audit_event_id is not None:
        payload["audit_event_id"] = audit_event_id
    if pattern_hit_kind is not None:
        payload["pattern_hit_kind"] = pattern_hit_kind

    assert_no_raw_secret(payload, path="$provider_policy_blocked_event_payload")
    await transition_with_event(
        session,
        run=run,
        to_state="blocked",
        event_type="policy_blocked",
        payload=payload,
        actor_id=actor_id,
        blocked_reason="policy_blocked",
        tenant_id=request.tenant_id,
    )


def _blocked_provider_result(
    *,
    request: ProviderRequest,
    decision: ComplianceDecision,
    status: Literal["data_class_deny", "preflight_deny"],
    pattern_hit_kind: str | None = None,
) -> ProviderResult:
    response_summary: dict[str, Any] = {
        "decision": "deny",
        "reason_code": decision.reason_code,
        "payload_data_class": decision.payload_data_class,
        "allowed_data_class": decision.allowed_data_class,
        "effective_allowed_data_class": decision.effective_allowed_data_class,
        "provider_compliance_matrix_version": decision.provider_compliance_matrix_version,
        "request_provider_compliance_matrix_version": _request_matrix_version(request),
        "matrix_version_mismatch": _matrix_version_mismatch(request, decision),
        "redacted": True,
    }
    if pattern_hit_kind is not None:
        response_summary["pattern_hit_kind"] = pattern_hit_kind

    return ProviderResult(
        status=status,
        artifact_ref=None,
        usage=None,
        model_resolved=request.model_resolved,
        api_version="compliance-gate-v1",
        sdk_version="taskmanagedai-internal",
        provider_request_fingerprint=_safe_provider_request_fingerprint(
            request,
            matrix_version=_request_matrix_version(request),
        ),
        error_code=decision.reason_code,
        error_summary=f"Provider request blocked before send: {decision.reason_code}",
        redacted_response_summary=response_summary,
        continuation_ref=None,
    )


def _safe_provider_request_fingerprint(
    request: ProviderRequest,
    *,
    matrix_version: str,
) -> str:
    try:
        return compute_provider_request_fingerprint(
            request,
            matrix_version=matrix_version,
            api_version="compliance-gate-v1",
            sdk_version="taskmanagedai-internal",
        )
    except ValueError:
        payload = request.model_dump(mode="json", exclude={"secret_capability_token"})
        return compute_payload_hash(payload)


def _assert_run_tenant_matches_request(run: AgentRun, request: ProviderRequest) -> None:
    run_tenant_id = getattr(run, "tenant_id", None)
    if run_tenant_id != request.tenant_id:
        raise ValueError("run tenant_id must match request tenant_id.")


def _payload_class_or_none(value: object) -> PayloadDataClass | None:
    if value in PAYLOAD_DATA_CLASS_ORDINAL:
        return cast(PayloadDataClass, value)
    return None


def _request_matrix_version(request: ProviderRequest) -> str:
    version = getattr(request, "provider_compliance_matrix_version", None)
    if not isinstance(version, str) or not version:
        return "unknown"
    return version


def _matrix_version(matrix: MatrixMapping, *, default: str) -> str:
    version = getattr(matrix, "matrix_version", None)
    if isinstance(version, str) and version:
        return version
    return default


def _matrix_version_mismatch(request: ProviderRequest, decision: ComplianceDecision) -> bool:
    return _request_matrix_version(request) != decision.provider_compliance_matrix_version


def _audit_event_id(event: object) -> str | None:
    event_id = getattr(event, "id", None)
    if event_id is None:
        return None
    return str(event_id)


def _min_data_class(left: PayloadDataClass, right: PayloadDataClass) -> PayloadDataClass:
    return left if data_class_ordinal(left) <= data_class_ordinal(right) else right


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_or_default(value: object, default: str) -> str:
    if value is None:
        return default
    text = str(value)
    return text if text else default


__all__ = ["ComplianceGate"]

