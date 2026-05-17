"""Sprint 12 batch 2 (BL-0140b): Ticket-to-PR smoke gold flow tests.

orchestrator skeleton の 6 stage 順序 + 失敗時 cascading skip + audit truth
invariant を AsyncMock-based で verify する.

real DB / provider / RepoProxy integration は SP-012 batch 3+ で
host migration drill + private staging E2E と統合.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from backend.app.services.integration.ticket_to_pr_smoke import (
    SMOKE_STAGE_ORDER,
    SmokeStage,
    TicketToPrSmokeError,
    TicketToPrSmokeResult,
    run_ticket_to_pr_smoke,
)

StageFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _make_succeeding_stage(
    stage_name: str, metadata: dict[str, Any] | None = None
) -> StageFn:
    """成功する stage callable factory (metadata を返す)。"""

    async def stage_fn(ctx: dict[str, Any]) -> dict[str, Any]:
        return {f"{stage_name}_ran": True, **(metadata or {})}

    return stage_fn


def _make_failing_stage(stage_name: str, error_msg: str = "stage error") -> StageFn:
    """失敗する stage callable factory (TicketToPrSmokeError raise)。"""

    async def stage_fn(ctx: dict[str, Any]) -> dict[str, Any]:
        raise TicketToPrSmokeError(f"{stage_name}: {error_msg}")

    return stage_fn


def _make_unexpected_failing_stage(error_type: type[Exception]) -> StageFn:
    """unexpected exception を raise する stage callable factory。"""

    async def stage_fn(ctx: dict[str, Any]) -> dict[str, Any]:
        raise error_type("unexpected boundary")

    return stage_fn


@pytest.mark.asyncio
async def test_smoke_stage_order_immutable() -> None:
    """SMOKE_STAGE_ORDER は固定 enum 順序 (Anti-Gaming、reorder 禁止)。"""
    assert SMOKE_STAGE_ORDER == (
        SmokeStage.TICKET,
        SmokeStage.RUN,
        SmokeStage.APPROVE,
        SmokeStage.REPO,
        SmokeStage.EVAL,
        SmokeStage.AUDIT,
    )
    assert len(SMOKE_STAGE_ORDER) == 6


@pytest.mark.asyncio
async def test_all_stages_succeed_overall_success_true() -> None:
    """6 stage 全件 succeeded → overall_success=True、cascading skip なし。"""
    result = await run_ticket_to_pr_smoke(
        ticket_callable=_make_succeeding_stage("ticket"),
        run_callable=_make_succeeding_stage("run"),
        approve_callable=_make_succeeding_stage("approve"),
        repo_callable=_make_succeeding_stage("repo"),
        eval_callable=_make_succeeding_stage("eval"),
        audit_callable=_make_succeeding_stage("audit"),
    )
    assert isinstance(result, TicketToPrSmokeResult)
    assert result.stage_count == 6
    assert result.succeeded_count == 6
    assert result.failed_count == 0
    assert result.skipped_count == 0
    assert result.overall_success is True
    assert [s.stage for s in result.stages] == list(SMOKE_STAGE_ORDER)
    for s in result.stages:
        assert s.status == "succeeded"
        assert s.error_code is None


@pytest.mark.asyncio
async def test_stage_failure_skips_subsequent_stages() -> None:
    """APPROVE stage 失敗 → REPO/EVAL/AUDIT は skipped (cascading)。"""
    result = await run_ticket_to_pr_smoke(
        ticket_callable=_make_succeeding_stage("ticket"),
        run_callable=_make_succeeding_stage("run"),
        approve_callable=_make_failing_stage("approve", "self-approval deny"),
        repo_callable=_make_succeeding_stage("repo"),
        eval_callable=_make_succeeding_stage("eval"),
        audit_callable=_make_succeeding_stage("audit"),
    )
    assert result.succeeded_count == 2  # ticket + run
    assert result.failed_count == 1  # approve
    assert result.skipped_count == 3  # repo + eval + audit
    assert result.overall_success is False

    # 順序確認
    assert result.stages[0].status == "succeeded"  # TICKET
    assert result.stages[1].status == "succeeded"  # RUN
    assert result.stages[2].status == "failed"  # APPROVE
    assert result.stages[3].status == "skipped"  # REPO
    assert result.stages[4].status == "skipped"  # EVAL
    assert result.stages[5].status == "skipped"  # AUDIT

    # cascading skip の error_code 確認
    for skipped_idx in (3, 4, 5):
        assert result.stages[skipped_idx].error_code == "cascaded_skip"


@pytest.mark.asyncio
async def test_first_stage_failure_skips_all_subsequent() -> None:
    """TICKET stage で即失敗 → 残 5 stage は全件 skipped。"""
    result = await run_ticket_to_pr_smoke(
        ticket_callable=_make_failing_stage("ticket"),
        run_callable=_make_succeeding_stage("run"),
        approve_callable=_make_succeeding_stage("approve"),
        repo_callable=_make_succeeding_stage("repo"),
        eval_callable=_make_succeeding_stage("eval"),
        audit_callable=_make_succeeding_stage("audit"),
    )
    assert result.succeeded_count == 0
    assert result.failed_count == 1
    assert result.skipped_count == 5
    assert result.overall_success is False
    assert result.stages[0].status == "failed"
    for i in range(1, 6):
        assert result.stages[i].status == "skipped"


@pytest.mark.asyncio
async def test_unexpected_exception_treated_as_failure() -> None:
    """TicketToPrSmokeError 以外の例外も failed として記録 + cascading skip。"""
    result = await run_ticket_to_pr_smoke(
        ticket_callable=_make_succeeding_stage("ticket"),
        run_callable=_make_unexpected_failing_stage(ValueError),
        approve_callable=_make_succeeding_stage("approve"),
        repo_callable=_make_succeeding_stage("repo"),
        eval_callable=_make_succeeding_stage("eval"),
        audit_callable=_make_succeeding_stage("audit"),
    )
    assert result.failed_count == 1
    assert result.skipped_count == 4
    assert result.stages[1].status == "failed"
    assert result.stages[1].error_code == "ValueError"


@pytest.mark.asyncio
async def test_stage_metadata_propagates_via_context() -> None:
    """stage の return metadata は次 stage の入力 ctx に merge される。"""

    seen_contexts: list[dict[str, Any]] = []

    async def ticket_fn(ctx: dict[str, Any]) -> dict[str, Any]:
        seen_contexts.append(dict(ctx))
        return {"ticket_id": "tk-001"}

    async def run_fn(ctx: dict[str, Any]) -> dict[str, Any]:
        seen_contexts.append(dict(ctx))
        return {"run_id": "ar-001"}

    async def approve_fn(ctx: dict[str, Any]) -> dict[str, Any]:
        seen_contexts.append(dict(ctx))
        return {"approval_id": "ap-001"}

    async def repo_fn(ctx: dict[str, Any]) -> dict[str, Any]:
        seen_contexts.append(dict(ctx))
        return {"pr_url": "https://example/pr/1"}

    async def eval_fn(ctx: dict[str, Any]) -> dict[str, Any]:
        seen_contexts.append(dict(ctx))
        return {"eval_passed": True}

    async def audit_fn(ctx: dict[str, Any]) -> dict[str, Any]:
        seen_contexts.append(dict(ctx))
        return {"audit_emitted": True}

    result = await run_ticket_to_pr_smoke(
        ticket_callable=ticket_fn,
        run_callable=run_fn,
        approve_callable=approve_fn,
        repo_callable=repo_fn,
        eval_callable=eval_fn,
        audit_callable=audit_fn,
        initial_context={"tenant_id": 1, "project_id": "proj-001"},
    )
    assert result.overall_success is True

    # 初期 context が ticket_fn に渡る
    assert seen_contexts[0] == {"tenant_id": 1, "project_id": "proj-001"}
    # ticket_fn の return が run_fn ctx に merge
    assert seen_contexts[1]["ticket_id"] == "tk-001"
    # run_fn の return が approve_fn ctx に merge
    assert seen_contexts[2]["run_id"] == "ar-001"
    assert seen_contexts[2]["ticket_id"] == "tk-001"  # 累積
    # 最終 audit_fn には全 stage の metadata が含まれる
    assert seen_contexts[5]["ticket_id"] == "tk-001"
    assert seen_contexts[5]["run_id"] == "ar-001"
    assert seen_contexts[5]["approval_id"] == "ap-001"
    assert seen_contexts[5]["pr_url"] == "https://example/pr/1"
    assert seen_contexts[5]["eval_passed"] is True


@pytest.mark.asyncio
async def test_non_dict_return_raises_smoke_error() -> None:
    """stage が dict 以外を返したら TicketToPrSmokeError raise (contract violation)。"""

    async def bad_ticket(ctx: dict[str, Any]) -> Any:  # noqa: ARG001
        return ["not", "a", "dict"]  # type: ignore[return-value]

    with pytest.raises(TicketToPrSmokeError, match="returned non-dict metadata"):
        await run_ticket_to_pr_smoke(
            ticket_callable=bad_ticket,
            run_callable=_make_succeeding_stage("run"),
            approve_callable=_make_succeeding_stage("approve"),
            repo_callable=_make_succeeding_stage("repo"),
            eval_callable=_make_succeeding_stage("eval"),
            audit_callable=_make_succeeding_stage("audit"),
        )


@pytest.mark.asyncio
async def test_result_is_frozen_dataclass() -> None:
    """TicketToPrSmokeResult / SmokeStageResult は frozen (append-only invariant)。"""
    result = await run_ticket_to_pr_smoke(
        ticket_callable=_make_succeeding_stage("ticket"),
        run_callable=_make_succeeding_stage("run"),
        approve_callable=_make_succeeding_stage("approve"),
        repo_callable=_make_succeeding_stage("repo"),
        eval_callable=_make_succeeding_stage("eval"),
        audit_callable=_make_succeeding_stage("audit"),
    )
    with pytest.raises(AttributeError):
        result.overall_success = False  # type: ignore[misc]
    with pytest.raises(AttributeError):
        result.stages[0].status = "failed"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_duration_ms_tracked_per_stage() -> None:
    """各 stage の duration_ms が非負 int で記録される。"""
    result = await run_ticket_to_pr_smoke(
        ticket_callable=_make_succeeding_stage("ticket"),
        run_callable=_make_succeeding_stage("run"),
        approve_callable=_make_succeeding_stage("approve"),
        repo_callable=_make_succeeding_stage("repo"),
        eval_callable=_make_succeeding_stage("eval"),
        audit_callable=_make_succeeding_stage("audit"),
    )
    for s in result.stages:
        assert s.duration_ms >= 0
        assert isinstance(s.duration_ms, int)
