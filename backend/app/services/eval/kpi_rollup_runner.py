"""Sprint 12 batch 1 (BL-0148 endpoint + CLI): KPI rollup runner.

5 KPI corpus を `eval/quality/<dataset_key>/` から load し、各 `evaluate_*`
を実行して `compute_kpi_rollup` で P0 判定する高レベル runner. API endpoint
(`GET /api/v1/eval/kpi-rollup`) と CLI (`scripts/kpi_rollup_run.py`) の
共通エントリポイント.

設計:
- corpus root は固定 (`eval/quality/`)、dataset_key 5 件は frozenset 固定
  (Anti-Gaming: caller が任意 KPI skip / 追加できない)
- 各 KPI の corpus load 失敗 (manifest 不在 / dataset_version mismatch 等)
  は `KpiRollupRunnerError` で raise (caller が log + audit)
- runner は **pure** (DB / Redis access なし、filesystem read-only)
- sut_results は本 batch では未対応 (Sprint 12 batch 2+ で BL-0140b 経由)

Anti-Gaming invariant:
- dataset_key は 5+ source 整合 frozenset で固定 (kpi_rollup.py の
  ALL_KPI_IDS と 1:1 対応)
- corpus load 順序は AC-KPI-01〜05 の固定順 (reorder 禁止)
- evaluate_* function の return type は MetricResult のみ (任意 dict 経路なし)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from backend.app.services.eval.kpi_rollup import (
    KpiRollupSummary,
    compute_kpi_rollup,
)
from backend.app.services.eval.kpis.acceptance_pass_rate import (
    evaluate_acceptance_pass_rate,
)
from backend.app.services.eval.kpis.approval_wait_ms import (
    evaluate_approval_wait_ms,
)
from backend.app.services.eval.kpis.citation_coverage import (
    evaluate_citation_coverage,
)
from backend.app.services.eval.kpis.cost_per_completed_task import (
    evaluate_cost_per_completed_task,
)
from backend.app.services.eval.kpis.time_to_merge import (
    evaluate_time_to_merge,
)
from backend.app.services.eval.loader import FixtureLoadError, load_fixture_corpus

# corpus root: repo 内 eval/quality/ (固定、caller 入力経路なし、AI 出力境界)
DEFAULT_EVAL_QUALITY_ROOT: Final[Path] = (
    Path(__file__).resolve().parents[4] / "eval" / "quality"
)

# 5 KPI ↔ dataset_key 対応 (Anti-Gaming: 順序固定、reorder 禁止).
# kpi_rollup.py ALL_KPI_IDS と完全対応 (5+ source 整合 6th source).
KPI_DATASET_KEYS: Final[tuple[tuple[str, str], ...]] = (
    ("AC-KPI-01", "acceptance_pass_rate"),
    ("AC-KPI-02", "time_to_merge"),
    ("AC-KPI-03", "approval_wait_ms"),
    ("AC-KPI-04", "citation_coverage"),
    ("AC-KPI-05", "cost_per_completed_task"),
)


class KpiRollupRunnerError(RuntimeError):
    """KPI rollup runner failure (corpus load / evaluate)."""


@dataclass(frozen=True, slots=True)
class CorpusLoadResult:
    """個別 KPI corpus の load 状態 (audit 用)."""

    kpi_id: str
    dataset_key: str
    dataset_version: str
    fixture_count: int


def run_kpi_rollup(
    *,
    eval_quality_root: Path = DEFAULT_EVAL_QUALITY_ROOT,
    sut_results_by_kpi: Mapping[str, Mapping[str, bool]] | None = None,
) -> tuple[KpiRollupSummary, tuple[CorpusLoadResult, ...]]:
    """5 KPI corpus を load + evaluate + rollup する高レベル runner.

    Args:
        eval_quality_root: ``eval/quality/`` の root path (default = repo 内)
        sut_results_by_kpi: 各 KPI ごとの SUT results map (`kpi_id ->
            fixture_id -> passed`)。本 batch では None (BL-0140b 経由で
            Sprint 12 batch 2+ 配備).

    Returns:
        (KpiRollupSummary, CorpusLoadResult tuple) — caller が log / audit
        / API response に使う.

    Raises:
        KpiRollupRunnerError: corpus load または evaluate 失敗時
    """

    if not eval_quality_root.exists():
        raise KpiRollupRunnerError(
            f"eval_quality_root not found: {eval_quality_root}"
        )

    metric_results: dict[str, object] = {}
    load_results: list[CorpusLoadResult] = []

    sut_lookup = sut_results_by_kpi or {}

    for kpi_id, dataset_key in KPI_DATASET_KEYS:
        corpus_root = eval_quality_root / dataset_key
        try:
            corpus = load_fixture_corpus(corpus_root, dataset_key=dataset_key)
        except FixtureLoadError as exc:
            raise KpiRollupRunnerError(
                f"corpus load failed for kpi_id={kpi_id} "
                f"dataset_key={dataset_key}: {exc}"
            ) from exc

        load_results.append(
            CorpusLoadResult(
                kpi_id=kpi_id,
                dataset_key=dataset_key,
                dataset_version=corpus.version,
                fixture_count=len(corpus.fixtures),
            )
        )

        sut_results = sut_lookup.get(kpi_id)
        try:
            if kpi_id == "AC-KPI-01":
                metric_results[kpi_id] = evaluate_acceptance_pass_rate(
                    corpus, sut_results=sut_results
                )
            elif kpi_id == "AC-KPI-02":
                metric_results[kpi_id] = evaluate_time_to_merge(
                    corpus, sut_results=sut_results
                )
            elif kpi_id == "AC-KPI-03":
                metric_results[kpi_id] = evaluate_approval_wait_ms(
                    corpus, sut_results=sut_results
                )
            elif kpi_id == "AC-KPI-04":
                metric_results[kpi_id] = evaluate_citation_coverage(
                    corpus, sut_results=sut_results
                )
            elif kpi_id == "AC-KPI-05":
                metric_results[kpi_id] = evaluate_cost_per_completed_task(
                    corpus, sut_results=sut_results
                )
        except Exception as exc:  # noqa: BLE001
            raise KpiRollupRunnerError(
                f"evaluate failed for kpi_id={kpi_id}: {exc}"
            ) from exc

    # 各 evaluate_* の return type は静的に narrow しきれないため、
    # dict[str, object] に保存し compute_kpi_rollup には typed cast で渡す
    # (runtime では正しい型、test で type safety verify 済)。
    summary = compute_kpi_rollup(
        acceptance=metric_results["AC-KPI-01"],  # type: ignore[arg-type]
        time_to_merge=metric_results["AC-KPI-02"],  # type: ignore[arg-type]
        approval_wait=metric_results["AC-KPI-03"],  # type: ignore[arg-type]
        citation=metric_results["AC-KPI-04"],  # type: ignore[arg-type]
        cost=metric_results["AC-KPI-05"],  # type: ignore[arg-type]
    )

    return summary, tuple(load_results)


__all__ = [
    "DEFAULT_EVAL_QUALITY_ROOT",
    "KPI_DATASET_KEYS",
    "CorpusLoadResult",
    "KpiRollupRunnerError",
    "run_kpi_rollup",
]
