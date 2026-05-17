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


def test_run_kpi_rollup_rejects_partial_sut_results_map() -> None:
    """Codex F-PR57-001 P2 adopt: sut_results_by_kpi が非 None で KPI key 欠落
    の場合 fail-closed (Anti-Gaming、KPI 未指定 caller を pass にしない)。
    """
    partial_map = {
        "AC-KPI-01": {"fixture-1": True},
        "AC-KPI-02": {"fixture-1": True},
        # AC-KPI-03, 04, 05 を意図的に omit
    }
    with pytest.raises(
        KpiRollupRunnerError,
        match="sut_results_by_kpi must contain exactly 5 keys",
    ):
        run_kpi_rollup(sut_results_by_kpi=partial_map)


def test_run_kpi_rollup_rejects_extraneous_sut_results_key() -> None:
    """sut_results_by_kpi に AC-KPI-NN 以外の key が含まれると fail-closed。"""
    extraneous_map = {
        "AC-KPI-01": {},
        "AC-KPI-02": {},
        "AC-KPI-03": {},
        "AC-KPI-04": {},
        "AC-KPI-05": {},
        "AC-KPI-99": {"fixture-fake": True},  # 不正な key
    }
    with pytest.raises(
        KpiRollupRunnerError,
        match=r"extraneous=\['AC-KPI-99'\]",
    ):
        run_kpi_rollup(sut_results_by_kpi=extraneous_map)


def test_run_kpi_rollup_accepts_full_sut_results_map() -> None:
    """5 KPI 全件 key が揃っていれば accept (empty dict は許容)。"""
    full_map = {
        "AC-KPI-01": {},
        "AC-KPI-02": {},
        "AC-KPI-03": {},
        "AC-KPI-04": {},
        "AC-KPI-05": {},
    }
    summary, _ = run_kpi_rollup(sut_results_by_kpi=full_map)
    # 全件 fixture-only evaluate に fallback (sut_results={} は evaluator に
    # よっては "no SUT" 扱いだが、本 test の主目的は full map accept verify)
    assert summary.kpi_count == 5


def test_run_kpi_rollup_default_none_sut_results_works() -> None:
    """default (sut_results_by_kpi=None) は従来通り全 KPI に None を渡す。"""
    summary, _ = run_kpi_rollup()
    assert summary.kpi_count == 5
