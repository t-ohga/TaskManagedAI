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

import json
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
from backend.app.domain.agent_runtime.status import (
    TERMINAL_STATES,
    AgentRunStatus,
    BlockedReason,
)
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
from backend.app.services.providers.usage_logger import (
    preflight_shadow_budget,
    preflight_shadow_request_tokens,
    record_provider_usage,
)

ProviderStepOutcome = Literal[
    "generated_artifact",
    "provider_refused",
    "provider_incomplete",
    "blocked_policy",
    "blocked_budget",
    "blocked_runtime",
    "failed_timeout",
    # SP-PHASE1 B5c (ADR-00048 §G/A-4): provider response 後の generation CAS で latch engage を検出し
    # usage/artifact/status を進めず discard/quarantine した。runtime_blocked (emergency_stop) で表現。
    "discarded_emergency_stop",
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
class ShadowCompletionStepResult:
    """Outcome of one ``execute_shadow_completion_step`` invocation (SP-029).

    shadow run の合法 terminal (``schema_validated -> completed`` を
    ``run_completed`` event で). production run はこの step を使えない
    (ValueError)。
    """

    to_state: AgentRunStatus
    event_type: AgentRunEventType
    event: AgentRunEvent


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

        # SP-PHASE1 B5c (ADR-00048 §G/A-4): emergency-stop latch CAS の preflight。Codex adversarial
        # P1-2/3/5 で active-only generation 比較の 3 つの穴が判明したため、monotonic generation
        # history (``max_generation_ever``) + preflight-active-fail に再設計する:
        #   - P1-2: latch が **既に active** な状態で step 開始すると、active-only 比較では preflight も
        #     postflight も同 active generation → discard されず provider.execute + usage/status が進行。
        #     → provider.execute の **前** に active なら即 deny する (新規 provider call をさせない)。
        #   - P1-3: preflight 後・provider.execute 前に engage → call は launch 済 → postflight で MAX が
        #     bump (G1 > G0) → discard。
        #   - P1-5: call 中に engage→clear が起きると active は preflight/postflight 共 None (active-only
        #     比較は等価で通してしまう穴) だが、cleared 行も MAX に残るため G1 > G0 → discard。
        #
        # (a) P1-2: latch が既に active なら provider.execute の **前** に EmergencyStopEngagedError を
        #     raise し、新規 provider call をさせない (latch 既 active での新規課金を構造的に防ぐ)。lock は
        #     ここでは取らない (call を通して保持せず engage を高速に保つ、A-4)。同期 in-flight call の中断
        #     不能性は A-4 honest limit として維持する。
        if await _read_emergency_stop_generation(self._session, run.tenant_id) is not None:
            from backend.app.services.superintendent.emergency_stop import (
                EmergencyStopEngagedError,
            )

            raise EmergencyStopEngagedError(run.tenant_id)
        # (b) P1-3/P1-5: monotonic MAX(generation) を snapshot (G0)。provider response 後に再読 (G1) し
        #     G1 > G0 (call window 中に engage が 1 回でも起きた) なら discard する。
        preflight_max_generation = await _read_max_emergency_stop_generation(
            self._session, run.tenant_id
        )

        # SP-029 (ADR-00055 §5、Codex R4 F-2): shadow run は provider 課金前に kill switch +
        # 既存累計 cap を preflight する。usage=None の合法レスポンスでも緊急停止を効かせ、
        # 既に cap 到達済みの shadow run の次 call を課金前に block する (post-execution の
        # record_provider_usage accumulator と二重で bound)。production run は no-op。
        shadow_preflight = await preflight_shadow_budget(
            self._session, run=run, actor_id=actor_id
        )
        if shadow_preflight is not None and shadow_preflight.exceeded:
            return _blocked_budget_result()

        # SP-029 (Codex R7): shadow の単一 call を request.max_tokens で課金前に上限化する
        # (max_tokens 未宣言 / 残 token cap 超過なら provider.execute せず block、overshoot 防止)。
        if run.run_mode == "shadow":
            shadow_request_bound = await preflight_shadow_request_tokens(
                self._session,
                run=run,
                actor_id=actor_id,
                request_max_tokens=request.max_tokens,
                estimated_input_tokens=_estimate_request_input_tokens(request),
            )
            if shadow_request_bound is not None and shadow_request_bound.exceeded:
                return _blocked_budget_result()

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
        target = _resolve_provider_transition_target(provider_result)

        # SP-PHASE1 B5c (ADR-00048 §G/A-4): provider response 後、record_provider_usage / artifact /
        # status の **前** に latch generation CAS。同一 tenant advisory lock 下で latch state を再読し、
        # 次のいずれかなら result を discard/quarantine して usage 記録・artifact 永続化・status 進行を
        # 行わない (runtime_blocked へ confine):
        #   - **currently active** (postflight で active latch あり) = call 中 or 直後に engage 済。
        #   - **G1 > G0** (monotonic MAX(generation) が call window 中に増加) = call window 中に engage が
        #     1 回でも起きた。engage→clear cycle (P1-5、active は両端 None) も MAX bump で捕捉する。
        # postflight は blocking advisory lock を取らない: monotonic MAX(generation) read が call window 中の
        # engage を検出でき (lock 不要)、discard transition の double-block は下の graceful re-read (LOW-4) が
        # 処理する。postflight で lock を保持すると、並行 engage (同一 key の advisory lock を取る) が postflight
        # transaction の commit まで block され、最悪 deadlock する (engage を高速に保つ A-4 方針にも反する)。
        postflight_active_generation = await _read_emergency_stop_generation(
            self._session, run.tenant_id
        )
        postflight_max_generation = await _read_max_emergency_stop_generation(
            self._session, run.tenant_id
        )
        # None-safe 比較: max_generation_ever は latch 履歴皆無なら None を返す。None を -1 (実 generation は
        # 非負なので最小) に正規化し、None>None / None>G の TypeError を避けつつ「call window 中に MAX が
        # 増加したか」を正しく判定する (None→G = 履歴皆無から engage = -1<G で discard、None→None = 変化なし)。
        _pre_max = preflight_max_generation if preflight_max_generation is not None else -1
        _post_max = (
            postflight_max_generation if postflight_max_generation is not None else -1
        )
        if postflight_active_generation is not None or _post_max > _pre_max:
            # adversarial LOW-4: concurrent engage が既に本 run を blocked へ遷移済の場合、status-guarded
            # transition (status == from_state) は 0-row → ValueError になる。これは「engage が先に block 済」
            # = 本来の意図 (=新規進行を止める) が既に達成された benign な状態なので、ungraceful ValueError を
            # surface させず discard 扱いで graceful return する (二重 block を試みない)。advisory lock 保持下
            # で DB status を再確認し、active latch 由来の block (blocked/terminal = もはや進行しない) なら
            # benign、それ以外 (依然 running 等) の予期せぬ 0-row は本物の不整合として re-raise する。
            try:
                event = await transition_with_event(
                    self._session,
                    run=run,
                    to_state="blocked",
                    event_type="runtime_blocked",
                    payload={
                        "reason_code": "emergency_stop_engaged",
                        "provider": request.provider,
                        "api_or_feature": request.api_or_feature,
                        "provider_result_kind": provider_result.status,
                        "preflight_max_generation": preflight_max_generation,
                        "postflight_max_generation": postflight_max_generation,
                        "postflight_active_generation": postflight_active_generation,
                    },
                    actor_id=actor_id,
                    blocked_reason="runtime_blocked",
                    idempotency_key=idempotency_key,
                )
            except ValueError:
                # held lock 下で current DB status を再読 (concurrent engage が block 済か確認)。
                await self._session.refresh(run)
                if run.status == "blocked" or run.status in TERMINAL_STATES:
                    # engage が先に block (or 既に terminal) = 新規進行は止まっており benign。新規 event は
                    # 積まず (engage 側が emergency_stop event を残す)、usage/artifact/status を進めず discard。
                    return ProviderStepResult(
                        outcome="discarded_emergency_stop",
                        to_state=run.status,
                        event_type="runtime_blocked",
                        event=None,
                        provider_result=provider_result,
                        compliance_decision=decision,
                        blocked_reason=run.blocked_reason,
                    )
                raise  # 依然 running 等の予期せぬ 0-row は本物の不整合として surface。
            return ProviderStepResult(
                outcome="discarded_emergency_stop",
                to_state="blocked",
                event_type="runtime_blocked",
                event=event,
                provider_result=provider_result,
                compliance_decision=decision,
                blocked_reason="runtime_blocked",
            )

        # SP-029 (Codex R7/R9/R13/R14 F-1): shadow run で provider.execute が返った (= 課金可能)
        # のに usage が **検証不能** だと cost/token を正しく計上できず cap を enforce できない。
        # **record_provider_usage の前** に、**status 不問** で usage=None または
        # ``usage.tokens_input <= 0`` を fail-closed (runtime_blocked) にする。実 provider call は
        # 必ず prompt の input token を伴うため tokens_input<=0 は usage 欠落の正規化 (0,0,0) =
        # unverifiable。成功 (generated_artifact) だけでなく provider_incomplete (timeout/max_token)
        # も対象にし、degraded response が record_provider_usage で 0 累積 → retry ループで cap を
        # 迂回するのを防ぐ。cost-only 欠落 (cost=0 だが token あり) は record_provider_usage の
        # token-floor が累積 cost を担保するため、ここでは block しない。
        usage = provider_result.usage
        if run.run_mode == "shadow" and (usage is None or usage.tokens_input <= 0):
            event = await transition_with_event(
                self._session,
                run=run,
                to_state="blocked",
                event_type="runtime_blocked",
                payload={
                    "reason_code": "shadow_usage_unverifiable",
                    "provider": request.provider,
                    "api_or_feature": request.api_or_feature,
                    "provider_result_kind": provider_result.status,
                    "run_mode": "shadow",
                },
                actor_id=actor_id,
                blocked_reason="runtime_blocked",
                idempotency_key=idempotency_key,
            )
            return ProviderStepResult(
                outcome="blocked_runtime",
                to_state="blocked",
                event_type="runtime_blocked",
                event=event,
                provider_result=provider_result,
                compliance_decision=decision,
                blocked_reason="runtime_blocked",
            )

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

    async def execute_shadow_completion_step(
        self,
        *,
        run: AgentRun,
        actor_id: UUID,
        idempotency_key: str | None = None,
    ) -> ShadowCompletionStepResult:
        """SP-029 (ADR-00055): shadow run を ``schema_validated -> completed`` で
        terminal 化する。

        shadow run は production state を汚さない試走であり、副作用 stage
        (``policy_linted`` / ``diff_ready`` / ``waiting_approval`` -> runner / repo /
        approval) を **一切通らず**、非 mutating な ``schema_validated`` から直接
        ``completed`` へ ``run_completed`` event で遷移する。この合法 terminal edge は
        state machine で run_mode-gated (``run_mode='shadow'`` のみ許可、production は
        ``transition_with_event`` 内の ``validate_transition`` で reject) されている。

        production run がこの step を呼ぶのは設計エラー (ValueError)。
        """

        if run.run_mode != "shadow":
            raise ValueError(
                "execute_shadow_completion_step requires run_mode='shadow'; "
                f"got run_mode={run.run_mode!r} (production runs must use the "
                "policy_lint -> diff_ready -> approval pipeline)."
            )

        event = await transition_with_event(
            self._session,
            run=run,
            to_state="completed",
            event_type="run_completed",
            payload={"run_mode": "shadow", "shadow_terminal": True},
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
        return ShadowCompletionStepResult(
            to_state="completed",
            event_type="run_completed",
            event=event,
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

        All reproducibility columns except ``evidence_set_hash`` are carried
        over. ``evidence_set_hash`` remains server-owned and is recomputed by
        ContextSnapshotRepository from a ResearchSetReference; resume retries
        without an active research binding receive the deterministic empty set
        hash instead of passing through caller-supplied hash material.
        """

        # F-PR22-001 P2 adopt: carry the prior server-emitted
        # ``evidence_set_hash`` forward via ``inherit_evidence_set_hash_from_snapshot_id``
        # so resume snapshots preserve the audit/diff trail of the original
        # research binding rather than collapsing to the empty-set placeholder.
        # The repository validates the previous snapshot exists in
        # (tenant_id, run_id) and loads the hash from the DB row — caller-
        # supplied hash material remains rejected at the signature boundary.
        return await create_snapshot(
            self._session,
            tenant_id=tenant_id,
            run_id=run_id,
            prompt_pack_version=previous_snapshot.prompt_pack_version,
            prompt_pack_lock=previous_snapshot.prompt_pack_lock,
            policy_version=previous_snapshot.policy_version,
            policy_pack_lock=previous_snapshot.policy_pack_lock,
            repo_state=previous_snapshot.repo_state,
            tool_manifest=previous_snapshot.tool_manifest,
            evidence_set_reference=None,
            inherit_evidence_set_hash_from_snapshot_id=previous_snapshot.id,
            provider_continuation_ref=previous_snapshot.provider_continuation_ref,
            provider_request_fingerprint=new_provider_request_fingerprint,
            snapshot_kind="resume",
        )


def _estimate_request_input_tokens(request: ProviderRequest) -> int:
    """prompt (messages) + structured_output_schema から保守的な input token 概算を返す。

    SP-029 (Codex R8/R9 F-2 / App F-2): shadow の per-call preflight で input spend を課金前に
    bound するための **tokenizer 非依存・over-estimate** な概算。serialized payload の
    **UTF-8 byte 数** を input token 上限とみなす。BPE token は最低 1 byte を符号化するため
    `actual_tokens <= byte_length` が **常に成立** し (codepoint 数だと emoji/ZWJ 系列で
    1 codepoint が複数 token になり過小評価しうるため byte で取る)、over-estimate = fail-safe で
    cap を早めに効かせる。secret_capability_token 等は含めない (messages + schema のみ)。
    """

    payload = request.model_dump(
        mode="json", include={"messages", "structured_output_schema"}
    )
    return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))


def _blocked_budget_result() -> ProviderStepResult:
    """shadow preflight (budget / request token) が block 済の際に返す共通 result。

    transition_with_event は preflight 側で実行済 (running -> blocked / budget_blocked) のため、
    ここでは re-transition せず outcome ラベルのみ surface する。"""

    return ProviderStepResult(
        outcome="blocked_budget",
        to_state="blocked",
        event_type="budget_blocked",
        event=None,
        provider_result=None,
        compliance_decision=None,
        blocked_reason="budget_blocked",
    )


async def _read_emergency_stop_generation(
    session: AsyncSession, tenant_id: int
) -> int | None:
    """active emergency-stop latch の generation を読む (B5c CAS、ADR-00048 §G/A-4)。

    active latch が無ければ ``None``、あれば monotonic generation (bigint) を返す。preflight 時点と
    provider response 後で本値を比較し、不一致 (None→gen / gen→gen' / gen→None ではない engage) なら
    engage が割り込んだと判定する。lazy import で循環を避ける (module-level 関数のため test が
    ``orchestrator._read_emergency_stop_generation`` を monkeypatch できる)。
    """
    from backend.app.services.superintendent.emergency_stop import EmergencyStopService

    latch = await EmergencyStopService(session).get_active(tenant_id)
    return latch.generation if latch is not None else None


async def _read_max_emergency_stop_generation(
    session: AsyncSession, tenant_id: int
) -> int:
    """全 latch 行 (cleared 含む) の monotonic MAX(generation) を読む (B5c P1-2/3/5、ADR-00048 §G/A-4)。

    engage 毎に +1、clear で減らない単調非減少値。provider call window の前後で本値を比較し、増加して
    いれば call window 中に engage が **1 回でも** 起きたと判定する (active-only 比較が見逃す
    engage→clear cycle (P1-5) や preflight-active 後の race を捕捉)。module-level 関数のため test が
    ``orchestrator._read_max_emergency_stop_generation`` を monkeypatch できる (lazy import で循環回避)。
    """
    from backend.app.services.superintendent.emergency_stop import EmergencyStopService

    return await EmergencyStopService(session).max_generation_ever(tenant_id)


async def _acquire_emergency_stop_lock(session: AsyncSession, tenant_id: int) -> None:
    """B5c CAS の tenant-scoped advisory lock 取得 (transaction-scoped、emergency_stop service と共有)。

    module-level wrapper のため test が ``orchestrator._acquire_emergency_stop_lock`` を monkeypatch
    できる (本体は emergency_stop の ``acquire_emergency_stop_lock`` へ委譲、lazy import で循環回避)。
    """
    from backend.app.services.superintendent.emergency_stop import (
        acquire_emergency_stop_lock,
    )

    await acquire_emergency_stop_lock(session, tenant_id)


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
    "ShadowCompletionStepResult",
    "ValidationStepOutcome",
    "ValidationStepResult",
]
