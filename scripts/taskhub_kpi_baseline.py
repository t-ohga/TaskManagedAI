"""SP022-T06 KPI baseline generator (Mac 単独 light mode).

`taskhub kpi-baseline --host <hostname> --output <path>` 経由で実行され、
`backend.app.services.eval.kpi_rollup_runner.run_kpi_rollup` の出力を
host metadata + computed_at + schema_version 付きで JSON に persist する。

SP-022 §142-145 で定義された SOP:
    taskhub kpi-baseline --host t-ohga-mac --output baselines/mac.json
    taskhub kpi-baseline --host t-ohga-vps --output baselines/vps.json
    taskhub kpi-baseline --host t-ohga-linux --output baselines/linux.json

SP-012 期間中は Mac 単独 baseline (light)、Linux/VPS は物理 host 取得後 SP-022
T09 implementation で追加。

Anti-Gaming invariant (Eval Anti-Gaming Rule):
- baseline 値は corpus fixture data ベース (SUT cross-check なし、sut_results=None)
- run_kpi_rollup 経由で 5 KPI 全件評価 + p0_accept 判定
- private_holdout fixture の expected 値は baseline 出力に含めない
- threshold_reason / not_threshold_met は audit trail として残す
"""

from __future__ import annotations

import json
import platform
import socket
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "BASELINE_SCHEMA_VERSION",
    "build_kpi_baseline_document",
    "main",
]

BASELINE_SCHEMA_VERSION: str = "1"


@dataclass(frozen=True, slots=True)
class HostMetadata:
    """baseline 文書に embed する host 情報 (forensic 用、PII なし)."""

    host_id: str  # operator が指定した logical host name (t-ohga-mac / -vps / -linux)
    platform_system: str  # platform.system() = Darwin / Linux
    platform_release: str  # platform.release() = kernel version
    python_version: str  # sys.version_info ベース
    machine: str  # platform.machine() = arm64 / x86_64
    uname_node: str  # socket.gethostname() (operator が --host と cross-check)


def collect_host_metadata(host_id: str) -> HostMetadata:
    """host info を inspect モジュールから収集 (no network、no shell exec)."""
    return HostMetadata(
        host_id=host_id,
        platform_system=platform.system(),
        platform_release=platform.release(),
        python_version=(
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ),
        machine=platform.machine(),
        uname_node=socket.gethostname(),
    )


def _kpi_entry_to_dict(entry: Any) -> dict[str, Any]:  # noqa: ANN401 - KpiEntry dataclass
    """KpiEntry dataclass を JSON-serializable dict に変換 (Anti-Gaming: minimum disclosure)."""
    return {
        "kpi_id": entry.kpi_id,
        "metric_value": entry.metric_value,
        "threshold_met": entry.threshold_met,
        "threshold_reason": entry.threshold_reason,
    }


def _corpus_load_result_to_dict(result: Any) -> dict[str, Any]:  # noqa: ANN401
    """CorpusLoadResult dataclass を dict に変換."""
    return {
        "kpi_id": result.kpi_id,
        "dataset_key": result.dataset_key,
        "dataset_version": result.dataset_version,
        "fixture_count": result.fixture_count,
    }


def build_kpi_baseline_document(
    host_id: str,
    *,
    rollup_summary: Any,  # noqa: ANN401 - KpiRollupSummary (循環 import 回避のため Any)
    corpus_load_results: tuple[Any, ...],
    computed_at: datetime | None = None,
    host_metadata: HostMetadata | None = None,
) -> dict[str, Any]:
    """baseline JSON document を構築する pure function (no I/O、test injectable).

    Args:
        host_id: operator が指定する logical host name
        rollup_summary: backend.app.services.eval.kpi_rollup.KpiRollupSummary
        corpus_load_results: CorpusLoadResult tuple
        computed_at: UTC datetime (None なら datetime.now(UTC))
        host_metadata: collect_host_metadata 結果 (None なら inspect で収集)

    Returns:
        JSON-serializable dict (operator が baselines/<host>.json に書込)
    """
    if computed_at is None:
        computed_at = datetime.now(UTC)
    if host_metadata is None:
        host_metadata = collect_host_metadata(host_id)

    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "host_id": host_id,
        "computed_at": computed_at.isoformat().replace("+00:00", "Z"),
        "host_metadata": {
            "host_id": host_metadata.host_id,
            "platform_system": host_metadata.platform_system,
            "platform_release": host_metadata.platform_release,
            "python_version": host_metadata.python_version,
            "machine": host_metadata.machine,
            "uname_node": host_metadata.uname_node,
        },
        "kpi_rollup": {
            "kpi_count": rollup_summary.kpi_count,
            "met_count": rollup_summary.met_count,
            "failed_count": rollup_summary.failed_count,
            "p0_accept": rollup_summary.p0_accept,
            "fail_tolerance": rollup_summary.fail_tolerance,
            "entries": [_kpi_entry_to_dict(e) for e in rollup_summary.entries],
        },
        "corpus_load_results": [
            _corpus_load_result_to_dict(r) for r in corpus_load_results
        ],
        "baseline_metadata": {
            "sut_results_provided": False,
            "anti_gaming_disclaimer": (
                "Baseline values reflect corpus fixture data only (no SUT cross-check). "
                "SUT-cross-check baseline は SP022-T08 batch 5+6 + SP-013 SUT integration 後に取得。"
            ),
            "scope": "mac_only" if "mac" in host_id.lower() else "other_host",
        },
    }


def write_baseline_to_path(document: dict[str, Any], output_path: Path) -> None:
    """baseline document を JSON file に atomic write (parent dir create + 0o644).

    Anti-Gaming: file content + permission のみ書込、git tree への commit は
    operator 責務 (private_holdout fixture 漏洩防止のため operator が手動 review)。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # atomic write via tempfile + rename (partial write 防止)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(output_path)
    output_path.chmod(0o644)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint (`taskhub kpi-baseline` 経由で呼ばれる).

    Returns:
        0: success
        2: argument error / corpus load fail
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="taskhub kpi-baseline",
        description="Compute KPI baseline for the local host (SP-022 T06)",
    )
    parser.add_argument(
        "--host",
        type=str,
        required=True,
        help="logical host id (e.g. t-ohga-mac / -vps / -linux)",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="output JSON path (e.g. baselines/mac.json)",
    )
    args = parser.parse_args(argv)

    # 遅延 import (循環依存防止 + test 用 monkey-patch)
    try:
        from backend.app.services.eval.kpi_rollup_runner import (
            KpiRollupRunnerError,
            run_kpi_rollup,
        )
    except ModuleNotFoundError as exc:
        print(f"ERROR: import failed: {exc}", file=sys.stderr)  # noqa: T201
        return 2

    try:
        rollup_summary, corpus_load_results = run_kpi_rollup()
    except KpiRollupRunnerError as exc:
        print(f"ERROR: KPI rollup failed: {exc}", file=sys.stderr)  # noqa: T201
        return 2

    document = build_kpi_baseline_document(
        args.host,
        rollup_summary=rollup_summary,
        corpus_load_results=corpus_load_results,
    )
    output_path = Path(args.output)
    write_baseline_to_path(document, output_path)
    print(  # noqa: T201
        f"KPI baseline written: {output_path} "
        f"(kpi_count={rollup_summary.kpi_count}, met={rollup_summary.met_count}, "
        f"failed={rollup_summary.failed_count}, p0_accept={rollup_summary.p0_accept})"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
