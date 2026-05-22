"""AgentRun runtime orchestrator (Sprint 5.5 BL-0067 / BL-0067 続き).

provider call → Compliance Gate → preflight → ProviderAdapter.execute →
record_provider_usage (BudgetGuard) → schema validate → repair retry →
transition_with_event の chain を統合する薄い service layer。caller (Sprint 6
で arq worker、Sprint 9 で UI、本 batch では unit test) は step method を順次
呼ぶ。

Sprint 4 Batch 4 で確立した ``transition_with_event`` 三重 guard (status update
+ event append + tenant context 確保を同一 transaction で実行) を **bypass せず**、
各 step が transition_with_event を呼ぶ形に統一する。state_machine の
``EVENT_TYPE_FOR_TRANSITION`` allowlist を経由するため、Sprint 5.5 batch 1 で
追加した ``repair_exhausted`` event_type が正しく allowlist 経由で append される。

### scope (Sprint 5.5 BL-0067 + BL-0067 続き、batch 1+2+3+4 累積)

- ``execute_provider_step`` (batch 2): running → {generated_artifact,
  provider_refused, provider_incomplete, blocked + reason, failed} の
  transition + AgentRunEvent
  - ``ComplianceGate.evaluate`` deny 経路で ``policy_blocked``
  - ``provider_request_preflight`` deny 経路で ``policy_blocked`` (canary / token pattern)
  - ``record_provider_usage`` を ``provider.execute`` 後に呼び、``BudgetGuard``
    hard exceed 時は ``blocked + budget_blocked`` 経路 (内部 transition 済み)
  - ``unsupported_schema`` / ``schema_mismatch`` は orchestrator 内で
    ``generated_artifact`` 経路に override (state machine 既存 allowlist
    `running -> validation_failed` 無いため、schema validation は別 step で実行)
- ``execute_repair_decision_step`` (batch 2): validation_failed → {running
  (retry), repair_exhausted (terminal)} の transition + ContextSnapshot
  snapshot_kind=resume
- ``execute_validation_step`` (batch 4 / BL-0067 続き): generated_artifact →
  {schema_validated, validation_failed} の transition + jsonschema Draft7
  validation + redacted error summary (raw artifact instance value 非 echo)

### 非 scope (Sprint 5.5 batch 4 で defer、Sprint 11 / 別 batch で対応)

- **DB integration full chain test**
  (``tests/runtime/test_agent_run_full_chain_integration.py``):
  provider call → Compliance Gate → preflight → execute →
  record_provider_usage → validate → repair retry → transition_with_event
  の full chain を実 DB で end-to-end。Docker postgres 起動済みでも host
  port mapping が確立できなかった batch 4 では unit + pure helper level
  に閉じる。次 Sprint で実装
- **audit_events 3 種** (``trust_level_promotion_audit`` /
  ``trust_level_promotion_denial_audit`` /
  ``output_validation_repair_retry_recorded``): AuditEventRepository への
  追加 + emit 経路は Sprint 11 / 別 batch
- **BL-0071 full eval-harness fixture loader**: Sprint 11 Eval Harness で
  AC-HARD-02 secret_canary loader (~1300 行) を踏襲して実装、本 batch では
  service-layer 5+ pattern を batch 3 で済
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.models.artifact import Artifact
from backend.app.db.models.context_snapshot import ContextSnapshot
from backend.app.domain.agent_runtime.event_type import AgentRunEventType
from backend.app.domain.agent_runtime.status import AgentRunStatus, BlockedReason
from backend.app.domain.provider.adapter import ProviderAdapter
from backend.app.domain.provider.compliance import ComplianceDecision
from backend.app.domain.provider.request import ProviderRequest
from backend.app.domain.provider.result import ProviderResult
from backend.app.repositories.context_snapshot import create_snapshot
from backend.app.services.agent_runtime.event_log import transition_with_event
from backend.app.services.agent_runtime.provider_result_mapping import (
    AgentRunStatusTransitionTarget,
    map_provider_result_to_status,
)
from backend.app.services.output_validator.core import RepairDecision, decide_repair
from backend.app.services.policy_pack.loader import PolicyPack, get_policy_pack
from backend.app.services.providers.compliance_gate import ComplianceGate
from backend.app.services.providers.preflight import provider_request_preflight
from backend.app.services.providers.usage_logger import record_provider_usage

ProviderStepOutcome = Literal[
    "generated_artifact",
    "provider_refused",
    "provider_incomplete",
    "blocked_policy",
    "blocked_budget",
    "blocked_runtime",
    "failed_timeout",
]

ValidationStepOutcome = Literal[
    "schema_validated",
    "validation_failed",
]


@dataclass(frozen=True)
class ValidationStepResult:
    """Outcome of one ``execute_validation_step`` invocation (BL-0067 続き).

    The ``validation_errors`` are redacted summaries (jsonschema path +
    validator + truncated message) so raw secret material from the artifact
    cannot leak into the event payload.
    """

    outcome: ValidationStepOutcome
    to_state: AgentRunStatus
    event_type: AgentRunEventType
    event: AgentRunEvent
    validation_passed: bool
    validation_errors: tuple[str, ...]


@dataclass(frozen=True)
class ProviderStepResult:
    """Outcome of one ``execute_provider_step`` invocation.

    ``event`` may be ``None`` for the ``blocked_budget`` outcome because
    ``record_provider_usage`` (via ``BudgetGuard.enforce_budget_or_block``)
    performs the ``running -> blocked`` transition internally; the caller
    receives the outcome label but no orchestrator-owned event handle.
    """

    outcome: ProviderStepOutcome
    to_state: AgentRunStatus
    event_type: AgentRunEventType
    event: AgentRunEvent | None
    provider_result: ProviderResult | None
    compliance_decision: ComplianceDecision | None
    blocked_reason: BlockedReason | None


@dataclass(frozen=True)
class RepairStepResult:
    """Outcome of one ``execute_repair_decision_step`` invocation."""

    decision: RepairDecision
    to_state: AgentRunStatus
    event_type: AgentRunEventType
    event: AgentRunEvent
    resume_snapshot: ContextSnapshot | None


class AgentRunOrchestrator:
    """Compose the provider / validate / repair chain over ``AgentRun``.

    The orchestrator does NOT own transaction boundaries; the caller wraps
    each step in ``async with session.begin():`` so that
    ``transition_with_event``, ``record_provider_usage`` and any subsequent
    inserts (artifact / context_snapshot) commit together.
    """

    def __init__(
        self,
        session: AsyncSession,
        compliance_gate: ComplianceGate,
        provider: ProviderAdapter,
        *,
        policy_pack: PolicyPack | None = None,
    ) -> None:
        self._session = session
        self._compliance_gate = compliance_gate
        self._provider = provider
        self._policy_pack = policy_pack

    @property
    def policy_pack(self) -> PolicyPack:
        return self._policy_pack if self._policy_pack is not None else get_policy_pack()

    async def execute_provider_step(
        self,
        *,
        run: AgentRun,
        request: ProviderRequest,
        actor_id: UUID,
        idempotency_key: str | None = None,
    ) -> ProviderStepResult:
        """Run one provider call cycle from the ``running`` state.

        Pipeline (fail-closed at each gate, SP55-B2-F-002/003/004 fixes):

        1. **tenant/run boundary guard**: ``run.tenant_id == request.tenant_id``
           AND ``run.id == request.run_id`` (SP55-B2-F-003).
        2. **ComplianceGate.evaluate deny** → ``policy_blocked``.
        3. **provider_request_preflight deny** → ``policy_blocked`` with
           ``reason_code='provider_request_preflight_violation'``
           (SP55-B2-F-002, secret canary / token pattern fail-closed).
        4. **provider.execute** → ProviderResult.
        5. **record_provider_usage** when ``usage is not None``: BudgetGuard
           hard-exceed → ``record_provider_usage`` performs the
           ``running -> blocked`` (budget_blocked) transition internally;
           orchestrator surfaces it as ``blocked_budget`` without re-transitioning
           (SP55-B2-F-004).
        6. **ProviderResultKind → AgentRunStatus mapping** with
           ``unsupported_schema`` / ``schema_mismatch`` overridden to
           ``generated_artifact`` (SP55-B2-F-001; the schema validation that
           produces ``validation_failed`` is the responsibility of a separate
           step, scheduled in Sprint 5.5 batch 3 BL-0067 continuation).
        7. ``transition_with_event`` with the matching event_type.
        """

        _assert_run_request_boundary(run, request)

        decision = self._compliance_gate.evaluate(request)
        if decision.decision == "deny":
            event = await transition_with_event(
                self._session,
                run=run,
                to_state="blocked",
                event_type="policy_blocked",
                payload=_compliance_deny_payload(decision, request),
                actor_id=actor_id,
                blocked_reason="policy_blocked",
                idempotency_key=idempotency_key,
            )
            return ProviderStepResult(
                outcome="blocked_policy",
                to_state="blocked",
                event_type="policy_blocked",
                event=event,
                provider_result=None,
                compliance_decision=decision,
                blocked_reason="policy_blocked",
            )

        preflight = provider_request_preflight(request)
        if preflight.decision == "deny":
            event = await transition_with_event(
                self._session,
                run=run,
                to_state="blocked",
                event_type="policy_blocked",
                payload={
                    "reason_code": "provider_request_preflight_violation",
                    "provider": request.provider,
                    "api_or_feature": request.api_or_feature,
                    "pattern_hit_kind": preflight.pattern_hit_kind,
                    "payload_data_class": decision.payload_data_class,
                    "allowed_data_class": decision.allowed_data_class,
                    "effective_allowed_data_class": decision.effective_allowed_data_class,
                    "provider_compliance_matrix_version": (
                        decision.provider_compliance_matrix_version
                    ),
                },
                actor_id=actor_id,
                blocked_reason="policy_blocked",
                idempotency_key=idempotency_key,
            )
            return ProviderStepResult(
                outcome="blocked_policy",
                to_state="blocked",
                event_type="policy_blocked",
                event=event,
                provider_result=None,
                compliance_decision=decision,
                blocked_reason="policy_blocked",
            )

        provider_result = self._provider.execute(request)

        if provider_result.usage is not None:
            budget_result = await record_provider_usage(
                self._session,
                run=run,
                usage=provider_result.usage,
                actor_id=actor_id,
                matrix_version=request.provider_compliance_matrix_version,
                expected_tenant_id=run.tenant_id,
            )
            if budget_result.exceeded:
                # record_provider_usage / BudgetGuard.enforce_budget_or_block has
                # already performed the running -> blocked (budget_blocked)
                # transition; we surface the outcome label without re-transitioning.
                return ProviderStepResult(
                    outcome="blocked_budget",
                    to_state="blocked",
                    event_type="budget_blocked",
                    event=None,
                    provider_result=provider_result,
                    compliance_decision=decision,
                    blocked_reason="budget_blocked",
                )

        target = _resolve_provider_transition_target(provider_result)
        outcome = _provider_outcome_for_target(provider_result.status, target)
        event_type = _provider_event_type_for_target(provider_result.status, target)

        event = await transition_with_event(
            self._session,
            run=run,
            to_state=target.status,
            event_type=event_type,
            payload=_provider_event_payload(provider_result, decision),
            actor_id=actor_id,
            blocked_reason=target.blocked_reason,
            idempotency_key=idempotency_key,
        )
        return ProviderStepResult(
            outcome=outcome,
            to_state=target.status,
            event_type=event_type,
            event=event,
            provider_result=provider_result,
            compliance_decision=decision,
            blocked_reason=target.blocked_reason,
        )

    async def execute_validation_step(
        self,
        *,
        run: AgentRun,
        artifact: Artifact,
        schema: dict[str, Any],
        actor_id: UUID,
        idempotency_key: str | None = None,
    ) -> ValidationStepResult:
        """Validate a freshly-generated artifact against the response schema.

        Pipeline (Sprint 5.5 BL-0067 続き、Sprint Pack §設計判断
        "validate → repair retry"):

        1. **tenant / run boundary guard**: ``artifact.tenant_id ==
           run.tenant_id`` AND ``artifact.run_id == run.id``.
        2. Run Draft-7 ``jsonschema`` validation on ``artifact.content_jsonb``
           with the supplied ``schema`` (caller passes the response schema
           from ProviderRequest.structured_output_schema or PlanArtifact's
           model_json_schema).
        3. Validation pass → ``generated_artifact → schema_validated``
           transition with ``schema_validated`` event_type.
        4. Validation fail → ``generated_artifact → validation_failed``
           transition with ``validation_failed`` event_type; redacted error
           summaries (first 5) are carried in the event payload, raw values
           are NOT echoed (BL-0068 redaction invariant carry-over).

        The actual ``repair_retry`` decision is owned by
        ``execute_repair_decision_step`` (Sprint 5.5 batch 2 BL-0064/0067);
        this step only resolves the schema-validation gate.
        """

        if artifact.tenant_id != run.tenant_id:
            raise ValueError(
                "artifact.tenant_id does not match run.tenant_id "
                "(validation step tenant boundary guard, BL-0067 続き)."
            )
        if artifact.run_id != run.id:
            raise ValueError(
                "artifact.run_id does not match run.id "
                "(validation step run boundary guard, BL-0067 続き)."
            )

        validator = Draft7Validator(schema)
        errors = sorted(
            validator.iter_errors(artifact.content_jsonb),
            key=lambda e: tuple(str(part) for part in e.absolute_path),
        )

        if not errors:
            event_payload: dict[str, Any] = {
                "artifact_id": str(artifact.id),
                "content_hash": artifact.content_hash,
                "payload_data_class": artifact.payload_data_class,
            }
            event = await transition_with_event(
                self._session,
                run=run,
                to_state="schema_validated",
                event_type="schema_validated",
                payload=event_payload,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
            return ValidationStepResult(
                outcome="schema_validated",
                to_state="schema_validated",
                event_type="schema_validated",
                event=event,
                validation_passed=True,
                validation_errors=(),
            )

        # Validation failed: redact error details + cap at first 5 to keep
        # event payload bounded.
        error_summaries = tuple(
            _redact_validation_error_summary(err) for err in errors[:5]
        )
        failed_payload: dict[str, Any] = {
            "artifact_id": str(artifact.id),
            "content_hash": artifact.content_hash,
            "payload_data_class": artifact.payload_data_class,
            "validation_error_count": len(errors),
            "validation_error_summaries": list(error_summaries),
        }
        event = await transition_with_event(
            self._session,
            run=run,
            to_state="validation_failed",
            event_type="validation_failed",
            payload=failed_payload,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
        return ValidationStepResult(
            outcome="validation_failed",
            to_state="validation_failed",
            event_type="validation_failed",
            event=event,
            validation_passed=False,
            validation_errors=error_summaries,
        )

    async def execute_repair_decision_step(
        self,
        *,
        run: AgentRun,
        retry_count: int,
        repair_budget_remaining: Decimal | int | float,
        actor_id: UUID,
        previous_snapshot: ContextSnapshot,
        new_provider_request_fingerprint: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> RepairStepResult:
        """Choose retry / repair_exhausted from a ``validation_failed`` state.

        Calls ``decide_repair`` (Sprint 5.5 BL-0064) to evaluate the policy
        AND budget AND-gate. On retry, transitions ``validation_failed →
        running`` with ``repair_retry_scheduled`` event AND creates a fresh
        ContextSnapshot with ``snapshot_kind='resume'`` so the run's 10-column
        provenance contract (DD-03 §10) is maintained. On exhaustion,
        transitions to ``repair_exhausted`` (terminal) with the dedicated
        ``repair_exhausted`` event_type (ADR-00004 §Sprint 5.5 update event #23).
        """

        if previous_snapshot.tenant_id != run.tenant_id:
            raise ValueError(
                "previous_snapshot.tenant_id must match run.tenant_id "
                "(ContextSnapshot carry-over boundary)."
            )
        if previous_snapshot.run_id != run.id:
            raise ValueError(
                "previous_snapshot.run_id must match run.id "
                "(ContextSnapshot carry-over boundary)."
            )

        decision = decide_repair(
            retry_count=retry_count,
            repair_budget_remaining=repair_budget_remaining,
            policy_pack=self.policy_pack,
        )

        if decision.outcome == "retry":
            event_payload: dict[str, Any] = {
                "retry_count_after": decision.retry_count_after,
                "policy_max_attempts": decision.policy_max_attempts,
                "repair_budget_remaining": str(decision.repair_budget_remaining),
            }
            event = await transition_with_event(
                self._session,
                run=run,
                to_state="running",
                event_type="repair_retry_scheduled",
                payload=event_payload,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
            resume_snapshot = await self._create_resume_snapshot(
                tenant_id=run.tenant_id,
                run_id=run.id,
                previous_snapshot=previous_snapshot,
                new_provider_request_fingerprint=new_provider_request_fingerprint,
            )
            return RepairStepResult(
                decision=decision,
                to_state="running",
                event_type="repair_retry_scheduled",
                event=event,
                resume_snapshot=resume_snapshot,
            )

        exhausted_payload: dict[str, Any] = {
            "retry_count_after": decision.retry_count_after,
            "policy_max_attempts": decision.policy_max_attempts,
            "repair_budget_remaining": str(decision.repair_budget_remaining),
            "exhaustion_reasons": list(decision.exhaustion_reasons),
        }
        event = await transition_with_event(
            self._session,
            run=run,
            to_state="repair_exhausted",
            event_type="repair_exhausted",
            payload=exhausted_payload,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
        return RepairStepResult(
            decision=decision,
            to_state="repair_exhausted",
            event_type="repair_exhausted",
            event=event,
            resume_snapshot=None,
        )

    async def _create_resume_snapshot(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        previous_snapshot: ContextSnapshot,
        new_provider_request_fingerprint: dict[str, Any],
    ) -> ContextSnapshot:
        """Derive a ``snapshot_kind='resume'`` snapshot from the previous one.

        All reproducibility columns except provider_request_fingerprint are
        carried over through repository-owned inheritance hooks. Hash and tool
        manifest material stays server-owned instead of being passed through
        caller-supplied parameters.
        """

        # F-PR22-001 P2 adopt: carry the prior server-emitted
        # ``evidence_set_hash`` forward via ``inherit_evidence_set_hash_from_snapshot_id``
        # so resume snapshots preserve the audit/diff trail of the original
        # research binding rather than collapsing to the empty-set placeholder.
        # The repository validates the previous snapshot exists in
        # (tenant_id, run_id) and loads the hash from the DB row — caller-
        # supplied hash or tool manifest material remains rejected at the
        # signature boundary.
        return await create_snapshot(
            self._session,
            tenant_id=tenant_id,
            run_id=run_id,
            prompt_pack_version=previous_snapshot.prompt_pack_version,
            prompt_pack_lock=previous_snapshot.prompt_pack_lock,
            policy_version=previous_snapshot.policy_version,
            policy_pack_lock=previous_snapshot.policy_pack_lock,
            repo_state=previous_snapshot.repo_state,
            evidence_set_reference=None,
            inherit_evidence_set_hash_from_snapshot_id=previous_snapshot.id,
            inherit_tool_manifest_from_snapshot_id=previous_snapshot.id,
            provider_continuation_ref=previous_snapshot.provider_continuation_ref,
            provider_request_fingerprint=new_provider_request_fingerprint,
            snapshot_kind="resume",
        )


def _assert_run_request_boundary(run: AgentRun, request: ProviderRequest) -> None:
    """Reject mismatched run / request before any provider-side work runs.

    SP55-B2-F-003: ``ComplianceGate.enforce`` performed this check at the
    Sprint 5 boundary; the orchestrator must re-assert it now that the
    provider path goes through ``evaluate`` (lighter) instead of
    ``enforce`` (heavier).
    """

    if run.tenant_id != request.tenant_id:
        raise ValueError(
            "run.tenant_id does not match request.tenant_id "
            "(tenant boundary guard, SP55-B2-F-003)."
        )
    if run.id != request.run_id:
        raise ValueError(
            "run.id does not match request.run_id "
            "(run boundary guard, SP55-B2-F-003)."
        )


def _resolve_provider_transition_target(
    provider_result: ProviderResult,
) -> AgentRunStatusTransitionTarget:
    """Apply orchestrator-local schema-mismatch override on top of the Sprint 5
    provider_result mapping.

    SP55-B2-F-001 fix: the canonical ``map_provider_result_to_status`` maps
    ``unsupported_schema`` / ``schema_mismatch`` to ``validation_failed``, but
    the state machine has no ``running -> validation_failed`` transition
    (validation_failed is only reachable from ``generated_artifact``). The
    orchestrator therefore routes those provider statuses through
    ``generated_artifact`` so the schema-validation step (a separate
    orchestrator method scheduled in Sprint 5.5 batch 3 BL-0067 continuation)
    is the one that ultimately yields ``validation_failed``.
    """

    base_target = map_provider_result_to_status(provider_result.status)
    if provider_result.status in ("unsupported_schema", "schema_mismatch"):
        return AgentRunStatusTransitionTarget(
            status="generated_artifact",
            blocked_reason=None,
            is_terminal=False,
        )
    return base_target


def _provider_outcome_for_target(
    kind: str,
    target: AgentRunStatusTransitionTarget,
) -> ProviderStepOutcome:
    """Translate the (kind, target) pair into a typed ``ProviderStepOutcome``."""

    if target.status == "generated_artifact":
        return "generated_artifact"
    if target.status == "provider_refused":
        return "provider_refused"
    if target.status == "provider_incomplete":
        return "provider_incomplete"
    if target.status == "failed":
        return "failed_timeout"
    if target.status == "blocked":
        if target.blocked_reason == "policy_blocked":
            return "blocked_policy"
        if target.blocked_reason == "budget_blocked":
            return "blocked_budget"
        if target.blocked_reason == "runtime_blocked":
            return "blocked_runtime"
    raise ValueError(
        f"unmapped provider outcome: kind={kind!r}, target={target!r}"
    )


def _provider_event_type_for_target(
    kind: str,
    target: AgentRunStatusTransitionTarget,
) -> AgentRunEventType:
    """Pick the AgentRunEvent type for a provider transition.

    Tied to ``EVENT_TYPE_FOR_TRANSITION`` in state_machine.py so transition
    + event remain in lock-step.
    """

    _ = kind
    if target.status == "generated_artifact":
        return "provider_responded"
    if target.status in ("provider_refused", "provider_incomplete"):
        return "provider_responded"
    if target.status == "blocked":
        if target.blocked_reason == "policy_blocked":
            return "policy_blocked"
        if target.blocked_reason == "budget_blocked":
            return "budget_blocked"
        if target.blocked_reason == "runtime_blocked":
            return "runtime_blocked"
    if target.status == "failed":
        return "run_failed"
    raise ValueError(
        f"unmapped provider event_type: kind={kind!r}, target={target!r}"
    )


def _compliance_deny_payload(
    decision: ComplianceDecision,
    request: ProviderRequest,
) -> dict[str, Any]:
    return {
        "reason_code": decision.reason_code,
        "provider": request.provider,
        "api_or_feature": request.api_or_feature,
        "payload_data_class": decision.payload_data_class,
        "allowed_data_class": decision.allowed_data_class,
        "effective_allowed_data_class": decision.effective_allowed_data_class,
        "provider_compliance_matrix_version": (
            decision.provider_compliance_matrix_version
        ),
    }


def _provider_event_payload(
    provider_result: ProviderResult,
    decision: ComplianceDecision,
) -> dict[str, Any]:
    """Build a raw-secret-free AgentRunEvent payload for a provider response.

    Only carries metadata + redacted_response_summary (Sprint 5 ProviderResult
    contract already guarantees no raw secret). ``compliance_decision`` adds
    Provider Compliance Matrix v2 ordinal labels for audit traceability.
    """

    return {
        "provider_result_kind": provider_result.status,
        "model_resolved": provider_result.model_resolved,
        "api_version": provider_result.api_version,
        "sdk_version": provider_result.sdk_version,
        "provider_request_fingerprint": provider_result.provider_request_fingerprint,
        "error_code": provider_result.error_code,
        "redacted_response_summary": provider_result.redacted_response_summary,
        "compliance_decision": decision.decision,
        "compliance_reason_code": decision.reason_code,
        "payload_data_class": decision.payload_data_class,
        "allowed_data_class": decision.allowed_data_class,
        "effective_allowed_data_class": decision.effective_allowed_data_class,
        "provider_compliance_matrix_version": decision.provider_compliance_matrix_version,
    }


def _redact_validation_error_summary(error: JsonSchemaValidationError) -> str:
    """Build a redacted summary of a jsonschema ValidationError.

    Only the JSON path + validator name + schema path is reported, not the
    instance value (which may contain raw secret material from the artifact
    even though Artifact's CHECK constraint scans for prohibited keys).
    """

    path = list(error.absolute_path)
    validator = error.validator or "<unknown>"
    schema_path = list(error.schema_path)
    # Truncate schema_path tail to avoid leaking nested schema labels that
    # could echo content (defense-in-depth; jsonschema labels are static
    # but the cap keeps payload size bounded).
    schema_path_tail = schema_path[-3:] if len(schema_path) > 3 else schema_path
    return (
        f"path={path} validator={validator} "
        f"schema_path={schema_path_tail}"
    )


__all__ = [
    "AgentRunOrchestrator",
    "ProviderStepOutcome",
    "ProviderStepResult",
    "RepairStepResult",
    "ValidationStepOutcome",
    "ValidationStepResult",
]
