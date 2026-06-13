"""AgentRun worker driver (SP-004-5 / ADR-00057).

SP-004 が「Sprint 4.5」へ defer した arq worker driver。``queued`` の **shadow**
AgentRun を、既存 orchestrator step (SP-004/5.5/SP-029) で end-to-end
(``queued -> completed``、Mock provider) に駆動する shadow-first foundational slice。

設計正本: ADR-00057 (accepted) + SP-004-5 Pack。plan-review R1-R4 (12 findings 全 adopt)
で硬化した invariant を実装する:

- **atomic claim (F3)**: ``SELECT ... FOR UPDATE`` で concurrent worker を直列化し、
  ``transition_with_event`` 内蔵の conditional UPDATE (``WHERE status == from_state``)
  で single-flight 化する。claim-miss は **benign no-op** (failed にしない)。
- **provenance binding (F4)**: ProviderRequest を先に構築し、ContextSnapshot ``input`` に
  その exact fingerprint を格納する (placeholder 禁止)。
- **non-terminal closure 分離 (F5 + R2-F3 + R3-F2)**: ``validation_failed`` は
  ``execute_repair_decision_step`` で ``repair_exhausted`` terminal に閉じ、
  ``provider_incomplete`` は **即 ``failed``** (durable retry counter 不在のため
  in-slice retry はしない)。
- **cancellation (F1 + R2-F2 + R3-F1)**: cooperative cancel は **post-commit DB status
  再読**を正本にする (``cancel_agent_run`` は commit せず caller が commit、signal は
  pre-commit best-effort)。driver は step 境界で run.status を refresh し ``cancelled``
  を検知したら graceful stop する (自分では cancelled へ遷移しない)。
- **error handling (R4-F1)**: 例外時は run を **現在の committed status から** ``failed``
  に終端化する (state machine の additive failed edge で全 driver-reachable state を網羅)。
  concurrent status-change (terminal / conditional update miss) は failed で上書きしない。

scope 外 (ADR-00057 §残課題): production runtime / real provider / durable retry /
worker-crash-mid-drive の自動 resume / provider mid-call kill。
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.context_snapshot import ContextSnapshot
from backend.app.db.session import AsyncSessionFactory
from backend.app.domain.agent_runtime.status import TERMINAL_STATES, AgentRunStatus
from backend.app.domain.provider.fingerprint import (
    compute_provider_request_fingerprint,
    provider_request_fingerprint_payload,
)
from backend.app.domain.provider.request import ProviderMessage, ProviderRequest
from backend.app.mcp.context import DEFAULT_SUPERINTENDENT_ACTOR_ID
from backend.app.repositories.artifact import ArtifactRepository, compute_content_hash
from backend.app.repositories.context_snapshot import create_snapshot
from backend.app.repositories.ticket import (
    ProjectArchivedError,
    TicketNotActionableError,
    TicketRepository,
)
from backend.app.services.agent_runtime.event_log import transition_with_event
from backend.app.services.agent_runtime.orchestrator import AgentRunOrchestrator
from backend.app.services.providers.compliance_gate import ComplianceGate
from backend.app.services.providers.matrix_loader import load_compliance_matrix
from backend.app.services.providers.mock import MockProviderAdapter
from backend.app.workers.active_registry_worker_gate import (
    verify_worker_dequeue_if_configured,
)

logger = logging.getLogger(__name__)

WorkerContext = MutableMapping[str, object]

# driver-initiated transition の actor。MCP bridge と同じ seeded system actor を使う。
_DRIVER_ACTOR_ID = DEFAULT_SUPERINTENDENT_ACTOR_ID

# config/provider_compliance.toml は repo root (backend/app/workers/ から 3 つ上)。
_COMPLIANCE_MATRIX_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "provider_compliance.toml"
)

# shadow driver の最小 structured output schema。MockProviderAdapter が
# ``_synthesize_schema_value`` で schema 準拠値を生成するため validation は pass する。
_SHADOW_DRIVER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"result": {"type": "string"}},
    "required": ["result"],
    "additionalProperties": False,
}

_DRIVER_PACK_LABEL = "agent-run-driver-shadow-v0"


def _driver_lock(scope: str) -> str:
    """ContextSnapshot の *_lock 列は sha256 hex。driver default を決定的に生成する。"""

    return hashlib.sha256(f"{scope}:{_DRIVER_PACK_LABEL}".encode()).hexdigest()


def _build_shadow_provider_request(
    run: AgentRun, matrix_version: str
) -> ProviderRequest:
    """shadow run の Mock ProviderRequest を構築する (F4: fingerprint の正本)。"""

    return ProviderRequest(
        tenant_id=run.tenant_id,
        run_id=run.id,
        provider="mock",
        api_or_feature="mock",
        model_resolved="mock-model",
        messages=[
            ProviderMessage(
                role="user",
                content="shadow run dry-run (agent_run_driver foundational slice).",
            )
        ],
        structured_output_schema=_SHADOW_DRIVER_SCHEMA,
        # driver default。shadow run は試走であり caller payload を持たないため固定。
        payload_data_class="internal",
        provider_compliance_matrix_version=matrix_version,
        max_tokens=512,
    )


async def _create_input_snapshot(
    session: AsyncSession,
    run: AgentRun,
    request: ProviderRequest,
    matrix_version: str,
    request_fingerprint_hash: str,
) -> ContextSnapshot:
    """ContextSnapshot ``input`` を 10 列で作成する (F4: exact fingerprint 格納)。

    ``provider_request_fingerprint`` には fingerprint payload (canonical 内容) に加え、
    その canonical hash (``fingerprint_sha256``) を埋め込む。これは ProviderResult が記録する
    ``provider_request_fingerprint`` (同 request の hash) と **一致する正本**で、driver が
    provider step 後に等価検証する (R1-A4: snapshot fp == result fp を実際に enforce)。
    """

    fingerprint_payload = provider_request_fingerprint_payload(
        request, matrix_version=matrix_version
    )
    fingerprint_payload["fingerprint_sha256"] = request_fingerprint_hash
    return await create_snapshot(
        session,
        tenant_id=run.tenant_id,
        run_id=run.id,
        prompt_pack_version=_DRIVER_PACK_LABEL,
        prompt_pack_lock=_driver_lock("prompt_pack"),
        policy_version=_DRIVER_PACK_LABEL,
        policy_pack_lock=_driver_lock("policy_pack"),
        repo_state={
            "commit_sha": "0" * 40,
            "branch": "shadow-driver",
            "dirty": False,
            "diff_hash": "0" * 64,
        },
        tool_manifest={
            "registry_version": _DRIVER_PACK_LABEL,
            "allowlist_hash": "0" * 64,
        },
        evidence_set_reference=None,  # 試走は research evidence を持たない (empty-set hash)。
        provider_continuation_ref=None,
        provider_request_fingerprint=fingerprint_payload,
        snapshot_kind="input",
    )


def _is_cancelled_or_terminal(status: AgentRunStatus) -> bool:
    return status == "cancelled" or status in TERMINAL_STATES


async def _assert_run_actionable(session: AsyncSession, run: AgentRun) -> None:
    """R4-A1: run の bound ticket が active かつ project が archived でないことを再検証する。

    ``bridge_run_create`` は作成時のみ actionable を guard するが、worker driver は run 作成後・
    dequeue 後に駆動するため、作成〜駆動の間に ticket soft-delete / project archive が起きうる
    (TOCTOU)。``bridge_run_update`` の advance guard と同じ invariant を server-owned
    ``run.project_id`` / ``run.ticket_id`` で再検証し、freeze 中の provider work / output 生成を
    防ぐ。frozen なら ``TicketNotActionableError`` / ``ProjectArchivedError`` を raise する
    (project row FOR UPDATE で archive/bulk-soft-delete と直列化。freeze 経路は project->tickets
    の lock 順で agent_runs を lock しないため driver の run->project 順と deadlock しない)。
    """

    await TicketRepository(session).assert_ticket_actionable(
        run.tenant_id, run.project_id, str(run.ticket_id)
    )


async def _reload_run(
    session: AsyncSession, *, run_id: UUID, tenant_id: int
) -> AgentRun:
    """run を最新の committed 状態で再取得する。

    step 境界で external cancel (cancel_agent_run が別 transaction で commit した
    ``cancelled``) を検知するための post-commit 再読。``session.refresh`` でなく再 fetch に
    することで claim 時の status narrowing をリセットし、各 step で現 status を正しく扱う。
    """

    # populate_existing=True: identity-map に残る run を DB の最新 committed 値で上書きする
    # (expire_on_commit 設定に依らず external cancel を確実に検知する)。
    run = await session.scalar(
        sa.select(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise RuntimeError(f"AgentRun {run_id} disappeared mid-drive")
    return run


async def execute_agent_run(
    ctx: WorkerContext,
    *,
    run_id: UUID | str,
    tenant_id: int,
) -> dict[str, Any]:
    """arq task: queued shadow AgentRun を end-to-end 駆動する。

    R4-F2: signature は keyword-only。enqueue も keyword
    (``enqueue_job("execute_agent_run", run_id=..., tenant_id=...)``) で投入すること
    (positional だと ``with_active_registry_gate`` wrapper の転送で TypeError になる)。
    """

    verify_worker_dequeue_if_configured(ctx)
    resolved_run_id = UUID(run_id) if isinstance(run_id, str) else run_id
    async with AsyncSessionFactory() as session:
        return await _drive_shadow_run(
            session, run_id=resolved_run_id, tenant_id=tenant_id
        )


async def _drive_shadow_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    tenant_id: int,
) -> dict[str, Any]:
    # R2-A1: claim 確認後の全 step (matrix load / request build / transition / snapshot /
    # 駆動) を単一 try で覆い、通常例外を fail-closed (現 status -> failed) に終端化する。
    # not-claimable は claim block 内で claim_miss return し補償しない (mutation なし)。
    try:
        # ---- 1. atomic claim + setup: queued -> gathering_context + ContextSnapshot(input) ----
        async with session.begin():
            run = await session.scalar(
                sa.select(AgentRun)
                .where(AgentRun.id == run_id, AgentRun.tenant_id == tenant_id)
                .with_for_update()
            )
            if run is None or run.run_mode != "shadow" or run.status != "queued":
                # not claimable: 既駆動 / production / 不在 / concurrent loser。benign no-op。
                # FOR UPDATE で直列化済のため loser はここで status != queued を読む (補償不要)。
                return {
                    "status": "claim_miss",
                    "run_id": str(run_id),
                    "reason": None if run is None else run.status,
                }
            # R4-A1: 作成後・dequeue 後に ticket soft-delete / project archive されていないか
            # 再検証する (freeze invariant)。frozen なら driver は駆動せず run を queued 据置で
            # skip する (freeze は可逆 = fail にしない、restore + 再 enqueue で駆動可能)。
            # claim block 内で catch し outer except (fail) へ伝播させない。
            try:
                await _assert_run_actionable(session, run)
            except (TicketNotActionableError, ProjectArchivedError):
                return {
                    "status": "skipped_not_actionable",
                    "run_id": str(run_id),
                    "reason": "ticket_or_project_frozen",
                }
            # 以降の matrix load / request build / transition / snapshot 失敗は claimable
            # 確認後の通常例外。outer except で queued->failed に補償する (R2-A1、silent orphan 防止)。
            matrix = load_compliance_matrix(_COMPLIANCE_MATRIX_PATH)
            matrix_version = matrix.matrix_version
            request = _build_shadow_provider_request(run, matrix_version)
            # F4: snapshot 格納する input 時点の request fingerprint hash (api/sdk "unknown")。
            request_fingerprint_hash = compute_provider_request_fingerprint(
                request, matrix_version=matrix_version
            )
            await transition_with_event(
                session,
                run=run,
                to_state="gathering_context",
                event_type="context_gathered",
                payload={"run_mode": "shadow", "driver": "agent_run_driver"},
                actor_id=_DRIVER_ACTOR_ID,
                tenant_id=tenant_id,
            )
            input_snapshot = await _create_input_snapshot(
                session, run, request, matrix_version, request_fingerprint_hash
            )

        orchestrator = AgentRunOrchestrator(
            session=session,
            compliance_gate=ComplianceGate(matrix_loader=matrix),
            provider=MockProviderAdapter(),
            policy_pack=None,
        )

        # ---- 2. gathering_context -> running ----
        async with session.begin():
            run = await _reload_run(session, run_id=run_id, tenant_id=tenant_id)
            if _is_cancelled_or_terminal(run.status):
                return {"status": run.status, "run_id": str(run_id)}
            await transition_with_event(
                session,
                run=run,
                to_state="running",
                event_type="provider_requested",
                payload={"run_mode": "shadow", "provider": "mock"},
                actor_id=_DRIVER_ACTOR_ID,
                tenant_id=tenant_id,
            )

        # ---- 3. provider step (running -> generated_artifact / blocked / provider_*) ----
        # R2-A2: provider.execute に渡す前の request を deep copy で正本化し、provenance 検証は
        # この pre-call 正本から再計算する (adapter が request を in-place mutate しても tamper 検知)。
        pre_call_request = request.model_copy(deep=True)
        async with session.begin():
            run = await _reload_run(session, run_id=run_id, tenant_id=tenant_id)
            if _is_cancelled_or_terminal(run.status):
                return {"status": run.status, "run_id": str(run_id)}
            # R4-A1: provider work (課金 / output) 直前に freeze を再検証する。claim 後に ticket
            # soft-delete / project archive された場合、ここで raise → outer except → running->failed
            # (mid-drive freeze は fail-closed。claim 時 skip と異なり既に running のため failed 終端)。
            await _assert_run_actionable(session, run)
            provider_step = await orchestrator.execute_provider_step(
                run=run, request=request, actor_id=_DRIVER_ACTOR_ID
            )
            # F4 + R2-A2 + R3-A1: ProviderResult を持つ **全 outcome** で、provider 遷移を commit
            # する **同一 transaction 内** で provenance を検証する。pre-call deep copy から result
            # 報告 api/sdk で再計算し result fingerprint と不一致なら **ここで raise して provider
            # 遷移ごと rollback** する (R3-A1: terminal provider_refused / provider_incomplete を
            # commit してから検証すると _fail_run_closed が terminal を上書きできず invalid な
            # 終端 result が残るため、commit 前に検証して running へ rollback → outer except で failed)。
            provider_result = provider_step.provider_result
            if provider_result is not None:
                expected_result_fingerprint = compute_provider_request_fingerprint(
                    pre_call_request,
                    matrix_version=matrix_version,
                    api_version=provider_result.api_version,
                    sdk_version=provider_result.sdk_version,
                )
                if (
                    provider_result.provider_request_fingerprint
                    != expected_result_fingerprint
                ):
                    raise RuntimeError(
                        "provenance fingerprint mismatch: ProviderResult fingerprint does "
                        "not match the pre-call ProviderRequest (F4 binding violation)"
                    )

        if provider_step.outcome != "generated_artifact":
            # blocked_* は resume 待ちで stop。provider_refused は既に terminal。
            # provider_incomplete は R3-F2 で即 failed に閉じる (durable retry なし)。
            if provider_step.outcome == "provider_incomplete":
                async with session.begin():
                    run = await _reload_run(session, run_id=run_id, tenant_id=tenant_id)
                    if run.status == "provider_incomplete":
                        await transition_with_event(
                            session,
                            run=run,
                            to_state="failed",
                            event_type="run_failed",
                            payload={
                                "reason_code": "provider_incomplete_no_retry",
                                "run_mode": "shadow",
                            },
                            actor_id=_DRIVER_ACTOR_ID,
                            tenant_id=tenant_id,
                        )
                run = await _reload_run(session, run_id=run_id, tenant_id=tenant_id)
            return {
                "status": run.status,
                "run_id": str(run_id),
                "outcome": provider_step.outcome,
            }

        # ---- 4. artifact 生成 + schema validation ----
        if provider_result is None:  # generated_artifact は result を伴う (防御的)
            raise RuntimeError(
                "execute_provider_step returned generated_artifact without provider_result"
            )
        content_jsonb = dict(provider_result.redacted_response_summary)
        async with session.begin():
            run = await _reload_run(session, run_id=run_id, tenant_id=tenant_id)
            if _is_cancelled_or_terminal(run.status):
                return {"status": run.status, "run_id": str(run_id)}
            # project_id は artifacts で NOT NULL (migration 0019)。module-level
            # create_artifact wrapper は project_id を渡さないため repository を直接使う。
            artifact = await ArtifactRepository(session).create_artifact(
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                run_id=run.id,
                kind="plan",
                content_hash=compute_content_hash(content_jsonb),
                content_jsonb=content_jsonb,
                payload_data_class=request.payload_data_class,
                exportable=False,
            )
            validation_step = await orchestrator.execute_validation_step(
                run=run,
                artifact=artifact,
                schema=request.structured_output_schema,
                actor_id=_DRIVER_ACTOR_ID,
            )

        if validation_step.outcome == "validation_failed":
            # F5 + R2-F3: validation_failed は execute_repair_decision_step で
            # repair_exhausted terminal に閉じる。foundational slice は durable retry
            # counter を持たないため repair_budget_remaining=0 で exhaustion に閉じる
            # (bounded retry loop は後続 increment)。
            async with session.begin():
                run = await _reload_run(session, run_id=run_id, tenant_id=tenant_id)
                if _is_cancelled_or_terminal(run.status):
                    return {"status": run.status, "run_id": str(run_id)}
                repair_step = await orchestrator.execute_repair_decision_step(
                    run=run,
                    retry_count=0,
                    repair_budget_remaining=0,
                    actor_id=_DRIVER_ACTOR_ID,
                    previous_snapshot=input_snapshot,
                    new_provider_request_fingerprint=provider_request_fingerprint_payload(
                        request, matrix_version=matrix_version
                    ),
                )
            run = await _reload_run(session, run_id=run_id, tenant_id=tenant_id)
            return {
                "status": run.status,
                "run_id": str(run_id),
                "repair_decision": repair_step.decision,
            }

        # ---- 5. shadow 完了: schema_validated -> completed ----
        async with session.begin():
            run = await _reload_run(session, run_id=run_id, tenant_id=tenant_id)
            if _is_cancelled_or_terminal(run.status):
                return {"status": run.status, "run_id": str(run_id)}
            await orchestrator.execute_shadow_completion_step(
                run=run, actor_id=_DRIVER_ACTOR_ID
            )
        return {"status": "completed", "run_id": str(run_id)}

    except Exception as exc:  # noqa: BLE001 - 全例外を fail-closed 終端化する
        await _fail_run_closed(
            session, run_id=run_id, tenant_id=tenant_id, exc=exc
        )
        return {"status": "failed", "run_id": str(run_id), "error_code": type(exc).__name__}


async def _fail_run_closed(
    session: AsyncSession,
    *,
    run_id: UUID,
    tenant_id: int,
    exc: Exception,
) -> None:
    """R4-F1: 例外時に run を現在の committed status から ``failed`` へ終端化する。

    全 driver-reachable non-terminal state からの ``failed`` edge (state_machine
    additive) を使い、固定 from-state を仮定しない。既に terminal / concurrent に
    status 変化した場合は no-op (cancelled 等を failed で上書きしない)。raw secret を
    payload に入れない (error type 名のみ)。
    """

    logger.exception(
        "agent_run_driver_failed",
        extra={"run_id": str(run_id), "tenant_id": tenant_id},
    )
    try:
        async with session.begin():
            run = await session.scalar(
                sa.select(AgentRun)
                .where(AgentRun.id == run_id, AgentRun.tenant_id == tenant_id)
                .with_for_update()
            )
            if run is None or run.status in TERMINAL_STATES:
                return
            await transition_with_event(
                session,
                run=run,
                to_state="failed",
                event_type="run_failed",
                payload={
                    "reason_code": "driver_exception",
                    "error_code": type(exc).__name__,
                    "run_mode": "shadow",
                },
                actor_id=_DRIVER_ACTOR_ID,
                tenant_id=tenant_id,
            )
    except Exception:  # noqa: BLE001 - 終端化失敗は元例外を握り潰さずログのみ
        logger.exception(
            "agent_run_driver_fail_close_error",
            extra={"run_id": str(run_id), "tenant_id": tenant_id},
        )


__all__ = ["execute_agent_run"]
