#!/usr/bin/env python3
"""KPI rollup CLI (Sprint 12 batch 1、BL-0148 CLI wrapper).

5 KPI corpus を load + evaluate + rollup し、P0 判定結果を JSON / human-readable
で出力する admin / cron script. API endpoint (`GET /api/v1/eval/kpi-rollup`)
と同じ `kpi_rollup_runner.run_kpi_rollup()` を呼ぶ.

Use cases:
- Sprint 12 P0 Acceptance での local verification (admin manual run)
- nightly cron (将来配備、本 script は CLI 経路のみ提供)
- BL-0149 P0 Exit sign-off の evidence 生成

CRITICAL invariant trace:
- pure (no DB / network access、filesystem read-only)
- caller-supplied 経路なし (eval_quality_root は fixed default)
- raw secret / capability token を含まない (Anti-Gaming + AC-HARD-02)

Usage:
    uv run python scripts/kpi_rollup_run.py [--json] [--eval-quality-root <path>]

Exit code:
    0: clean (p0_accept=True)
    1: p0_accept=False (改善 Sprint が必要)
    2: CLI usage error / corpus load error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# repo root を sys.path に追加 (uv run 経由でも import 可能に)
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.app.services.eval.kpi_rollup_runner import (  # noqa: E402
    DEFAULT_EVAL_QUALITY_ROOT,
    KpiRollupRunnerError,
    run_kpi_rollup,
)


def _format_human(summary: object, load_results: object) -> str:
    """human-readable text output (CLI default)."""

    # summary / load_results は KpiRollupSummary / tuple[CorpusLoadResult, ...]
    lines = []
    lines.append("=" * 60)
    lines.append("KPI Rollup Summary (BL-0148)")
    lines.append("=" * 60)
    lines.append(
        f"p0_accept: {summary.p0_accept}   "  # type: ignore[attr-defined]
        f"(met {summary.met_count} / failed {summary.failed_count} "  # type: ignore[attr-defined]
        f"/ tolerance {summary.fail_tolerance})"  # type: ignore[attr-defined]
    )
    lines.append("-" * 60)
    for entry in summary.entries:  # type: ignore[attr-defined]
        status_glyph = "OK " if entry.threshold_met else "FAIL"
        value_repr = (
            "undefined" if entry.metric_value is None else f"{entry.metric_value}"
        )
        reason = entry.threshold_reason or ""
        lines.append(
            f"  [{status_glyph}] {entry.kpi_id} {entry.metric_key:30s} "
            f"value={value_repr:15s} reason={reason}"
        )
    lines.append("-" * 60)
    lines.append("Corpus loads:")
    for lr in load_results:  # type: ignore[union-attr]
        lines.append(
            f"  {lr.kpi_id} dataset_key={lr.dataset_key:30s} "
            f"version={lr.dataset_version} fixtures={lr.fixture_count}"
        )
    lines.append("=" * 60)
    return "\n".join(lines)


def _format_json(summary: object, load_results: object) -> str:
    """JSON output (CI / programmatic consumption)."""

    payload = {
        "kpi_count": summary.kpi_count,  # type: ignore[attr-defined]
        "met_count": summary.met_count,  # type: ignore[attr-defined]
        "failed_count": summary.failed_count,  # type: ignore[attr-defined]
        "p0_accept": summary.p0_accept,  # type: ignore[attr-defined]
        "fail_tolerance": summary.fail_tolerance,  # type: ignore[attr-defined]
        "entries": [
            {
                "kpi_id": e.kpi_id,
                "metric_key": e.metric_key,
                "metric_value": e.metric_value,
                "threshold_met": e.threshold_met,
                "threshold_reason": e.threshold_reason,
            }
            for e in summary.entries  # type: ignore[attr-defined]
        ],
        "corpus_loads": [
            {
                "kpi_id": lr.kpi_id,
                "dataset_key": lr.dataset_key,
                "dataset_version": lr.dataset_version,
                "fixture_count": lr.fixture_count,
            }
            for lr in load_results  # type: ignore[union-attr]
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "KPI Rollup CLI (BL-0148): "
            "evaluate 5 P0 KPIs and emit P0 acceptance decision"
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (default: human-readable text)",
    )
    parser.add_argument(
        "--eval-quality-root",
        type=Path,
        default=None,
        help=f"override eval/quality root path (default: {DEFAULT_EVAL_QUALITY_ROOT})",
    )
    args = parser.parse_args()

    try:
        summary, load_results = run_kpi_rollup(
            eval_quality_root=(
                args.eval_quality_root
                if args.eval_quality_root is not None
                else DEFAULT_EVAL_QUALITY_ROOT
            ),
        )
    except KpiRollupRunnerError as exc:
        print(f"ERROR: KPI rollup runner failed: {exc}", file=sys.stderr)  # noqa: T201
        return 2

    if args.json:
        print(_format_json(summary, load_results))  # noqa: T201
    else:
        print(_format_human(summary, load_results))  # noqa: T201

    return 0 if summary.p0_accept else 1


if __name__ == "__main__":
    sys.exit(main())
