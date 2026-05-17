"""Sprint 12 batch 1 (BL-0148 endpoint): KPI rollup API endpoint.

`GET /api/v1/eval/kpi-rollup` — 5 KPI corpus を load + evaluate + rollup
し、P0 判定 (`p0_accept`) と各 KPI の threshold_met 状態を返す.

設計:
- read-only endpoint (GET、副作用なし、DB / external API 呼出なし)
- actor + tenant context dependency 必須 (login required)
- response は frozen Pydantic model (append-only invariant、JSON encoding 安定)
- KPI fixture corpus 読み込みは pure filesystem read、AI 出力直結なし
- caller-supplied 経路なし (eval_quality_root は fixed default)

Security boundary:
- Provider Compliance / SecretBroker / runner gateway は不変 (本 endpoint は
  pure read-only aggregation、provider call / runner / secret access なし)
- raw secret / capability token は response に含まない (各 evaluate_* で
  pure metric_value / threshold_met / threshold_reason のみ)
"""

from __future__ import annotations

import logging
from typing import Final, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.approval_inbox import get_current_actor_id, get_tenant_id
from backend.app.services.eval.kpi_rollup_runner import (
    KpiRollupRunnerError,
    run_kpi_rollup,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/eval", tags=["eval"])


class KpiEntryResponse(BaseModel):
    """単一 KPI の集計 entry (frozen、API response)."""

    model_config = ConfigDict(frozen=True)

    kpi_id: Literal[
        "AC-KPI-01", "AC-KPI-02", "AC-KPI-03", "AC-KPI-04", "AC-KPI-05"
    ] = Field(description="P0 KPI ID (固定 enum 5 件).")
    metric_key: str = Field(min_length=1, description="metric snake_case key.")
    metric_value: float | None = Field(
        description="recomputed metric (corpus undefined なら null)."
    )
    threshold_met: bool = Field(
        description="threshold passed (corpus undefined なら false)."
    )
    threshold_reason: str | None = Field(
        default=None, description="reason code (e.g. 'threshold_met')."
    )


class CorpusLoadResponse(BaseModel):
    """個別 KPI corpus load 状態 (audit / debug)."""

    model_config = ConfigDict(frozen=True)

    kpi_id: str = Field(min_length=1)
    dataset_key: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    fixture_count: int = Field(ge=0)


class KpiRollupResponse(BaseModel):
    """KPI rollup API response (frozen、JSON encoding 安定)."""

    model_config = ConfigDict(frozen=True)

    kpi_count: int = Field(description="常に 5 (固定 KPI enum).")
    met_count: int = Field(ge=0, description="threshold_met=True 数.")
    failed_count: int = Field(ge=0, description="threshold_met=False 数.")
    p0_accept: bool = Field(
        description="P0 判定 (未達 <= fail_tolerance なら True)."
    )
    fail_tolerance: int = Field(
        description="P0 fail tolerance (PRD-01 §AC-KPI、現状 1)."
    )
    entries: tuple[KpiEntryResponse, ...] = Field(
        description="5 KPI entries (AC-KPI-01..05 順)."
    )
    corpus_loads: tuple[CorpusLoadResponse, ...] = Field(
        description="各 KPI corpus load 状態 (audit)."
    )


# tenant_id は acceptance dependency として参照のみ (KPI corpus は repo 内
# fixed path、tenant 跨ぎなし)。actor_id も同様 (authentication 必須のみ).
_ACTOR_DEP: Final = Depends(get_current_actor_id)
_TENANT_DEP: Final = Depends(get_tenant_id)


@router.get("/kpi-rollup", response_model=KpiRollupResponse)
async def get_kpi_rollup(
    _actor_id: object = _ACTOR_DEP,
    _tenant_id: int = _TENANT_DEP,
) -> KpiRollupResponse:
    """KPI rollup を取得 (5 KPI 全件 evaluate + P0 判定).

    Returns:
        KpiRollupResponse with 5 entries, p0_accept gate, corpus_loads audit.

    Raises:
        503: corpus load 失敗 (manifest 不在 / dataset_version mismatch).
    """

    try:
        summary, load_results = run_kpi_rollup()
    except KpiRollupRunnerError as exc:
        logger.warning("kpi_rollup_corpus_load_failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "kpi_rollup_corpus_load_failed",
                "error_summary": str(exc),
            },
        ) from exc

    entries = tuple(
        KpiEntryResponse(
            kpi_id=e.kpi_id,
            metric_key=e.metric_key,
            metric_value=e.metric_value,
            threshold_met=e.threshold_met,
            threshold_reason=e.threshold_reason,
        )
        for e in summary.entries
    )
    corpus_loads = tuple(
        CorpusLoadResponse(
            kpi_id=lr.kpi_id,
            dataset_key=lr.dataset_key,
            dataset_version=lr.dataset_version,
            fixture_count=lr.fixture_count,
        )
        for lr in load_results
    )

    return KpiRollupResponse(
        kpi_count=summary.kpi_count,
        met_count=summary.met_count,
        failed_count=summary.failed_count,
        p0_accept=summary.p0_accept,
        fail_tolerance=summary.fail_tolerance,
        entries=entries,
        corpus_loads=corpus_loads,
    )


__all__ = [
    "CorpusLoadResponse",
    "KpiEntryResponse",
    "KpiRollupResponse",
    "router",
]
