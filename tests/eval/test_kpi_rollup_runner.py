"""Sprint 12 batch 1 (BL-0148 runner): kpi_rollup_runner integration tests.

実 `eval/quality/` corpus を読み込み、5 KPI 全件 evaluate + rollup できることを
verify する integration test (DB / network 不要、filesystem read のみ).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.services.eval.kpi_rollup import KpiRollupSummary
from backend.app.services.eval.kpi_rollup_runner import (
    DEFAULT_EVAL_QUALITY_ROOT,
    KPI_DATASET_KEYS,
    KpiRollupRunnerError,
    run_kpi_rollup,
)

_EXPECTED_KPI_DATASET_KEYS = (
    ("AC-KPI-01", "acceptance_pass_rate"),
    ("AC-KPI-02", "time_to_merge"),
    ("AC-KPI-03", "approval_wait_ms"),
    ("AC-KPI-04", "citation_coverage"),
    ("AC-KPI-05", "cost_per_completed_task"),
)


def test_default_eval_quality_root_exists() -> None:
    """default corpus root が repo 内に存在する。"""
    assert DEFAULT_EVAL_QUALITY_ROOT.exists(), (
        f"eval/quality root missing: {DEFAULT_EVAL_QUALITY_ROOT}"
    )
    assert DEFAULT_EVAL_QUALITY_ROOT.is_dir()


def test_kpi_dataset_keys_immutable_order() -> None:
    """KPI_DATASET_KEYS は AC-KPI-01..05 の固定順 (reorder 禁止)。"""
    assert KPI_DATASET_KEYS == _EXPECTED_KPI_DATASET_KEYS


def test_run_kpi_rollup_with_real_corpus() -> None:
    """real eval/quality fixture corpus で 5 KPI evaluate + rollup 成功。"""
    summary, load_results = run_kpi_rollup()

    assert isinstance(summary, KpiRollupSummary)
    assert summary.kpi_count == 5
    assert summary.met_count + summary.failed_count == 5
    assert len(summary.entries) == 5
    assert len(load_results) == 5

    # AC-KPI-01..05 順 invariant
    assert [e.kpi_id for e in summary.entries] == [
        kpi_id for kpi_id, _ in _EXPECTED_KPI_DATASET_KEYS
    ]
    assert [lr.kpi_id for lr in load_results] == [
        kpi_id for kpi_id, _ in _EXPECTED_KPI_DATASET_KEYS
    ]
    # dataset_key 一致
    for lr, (_, expected_key) in zip(load_results, _EXPECTED_KPI_DATASET_KEYS, strict=True):
        assert lr.dataset_key == expected_key


def test_run_kpi_rollup_raises_on_missing_root(tmp_path: Path) -> None:
    """eval_quality_root が不在なら KpiRollupRunnerError raise。"""
    missing = tmp_path / "no-such-corpus"
    with pytest.raises(KpiRollupRunnerError, match="eval_quality_root not found"):
        run_kpi_rollup(eval_quality_root=missing)


def test_run_kpi_rollup_raises_on_partial_corpus(tmp_path: Path) -> None:
    """eval_quality_root に 1 KPI の corpus しかない → 残 KPI load 失敗。"""
    partial = tmp_path / "partial-eval-quality"
    partial.mkdir()
    # 何もない dir を作って 5 KPI 全件 load 失敗を誘発
    with pytest.raises(KpiRollupRunnerError, match="corpus load failed"):
        run_kpi_rollup(eval_quality_root=partial)
