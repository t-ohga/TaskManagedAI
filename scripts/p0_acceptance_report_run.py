#!/usr/bin/env python3
"""P0 Acceptance Report CLI (Sprint 12 batch 6、BL-0149 evidence chain).

`scripts/p0_acceptance_report_run.py --input <path>` で 7 source の JSON file を
読み、`run_p0_acceptance_report` を呼んで artifact + audit_payload を出力する.

Use cases:
- BL-0149 P0 Exit sign-off step (user 物理 drill 完了後の evidence aggregation)
- nightly cron (将来配備、本 script は CLI 経路のみ提供)
- audit_events.p0_acceptance_report_generated emit の input 生成

CRITICAL invariant:
- pure (no DB / network、filesystem read-only)
- raw secret / capability token を含まない (artifact / audit_payload とも)
- input JSON は caller の責務、本 script は schema validation で reject

Usage:
    uv run python scripts/p0_acceptance_report_run.py --input <path> [--json]

Exit code:
    0: clean (p0_exit_decision=True)
    1: p0_exit_decision=False (deficiency あり、改善 Sprint or user fix 必要)
    2: CLI usage error / input JSON parse error / contract validation error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.app.services.eval.acceptance_artifact_builder import (  # noqa: E402
    P0AcceptanceArtifact,
)
from backend.app.services.eval.p0_acceptance_audit_emit import (  # noqa: E402
    build_p0_acceptance_audit_payload,
)
from backend.app.services.eval.p0_acceptance_report_runner import (  # noqa: E402
    P0AcceptanceReportRunOutput,
)


def _format_human(output: P0AcceptanceReportRunOutput) -> str:
    """human-readable text output (CLI default)."""

    report = output.report
    artifact = output.artifact
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("P0 Acceptance Report (BL-0149)")
    lines.append("=" * 70)
    lines.append(
        f"p0_exit_decision: {report.p0_exit_decision}   "
        f"(deficiency_count={len(report.deficiencies)})"
    )
    lines.append("-" * 70)
    lines.append("Sources:")
    lines.append(f"  hard_gates_accept:        {report.hard_gates_accept}")
    lines.append(f"  kpi_accept:               {report.kpi_accept}")
    lines.append(f"  smoke_success:            {report.smoke_success}")
    lines.append(f"  host_migration_passed:    {report.host_migration_passed}")
    lines.append(f"  backup_restore_passed:    {report.backup_restore_passed}")
    lines.append(f"  private_staging_passed:   {report.private_staging_passed}")
    lines.append(f"  gated_rows_satisfied:     {report.gated_rows_satisfied}")
    if report.deficiencies:
        lines.append("-" * 70)
        lines.append("Deficiencies:")
        for d in report.deficiencies:
            lines.append(f"  - {d}")
    lines.append("-" * 70)
    lines.append("Hash chain (server-owned, append-only audit truth):")
    hc = artifact.hash_chain
    lines.append(f"  final_chain_sha256:       {hc.final_chain_sha256}")
    lines.append(f"  hard_gates_sha256:        {hc.hard_gates_sha256}")
    lines.append(f"  kpi_sha256:               {hc.kpi_sha256}")
    lines.append(f"  smoke_sha256:             {hc.smoke_sha256}")
    lines.append(f"  drill_entries_sha256:     {hc.drill_entries_sha256}")
    lines.append(f"  private_staging_sha256:   {hc.private_staging_sha256}")
    lines.append(f"  gated_rows_sha256:        {hc.gated_rows_sha256}")
    lines.append("=" * 70)
    return "\n".join(lines)


def _artifact_to_dict(artifact: P0AcceptanceArtifact) -> dict[str, Any]:
    """P0AcceptanceArtifact 全文を JSON-serializable dict に変換."""
    hc = artifact.hash_chain
    return {
        "schema_version": artifact.schema_version,
        "timestamp": artifact.timestamp,
        "p0_exit_decision": artifact.p0_exit_decision,
        "deficiencies": list(artifact.deficiencies),
        "hash_chain": {
            "schema_version": hc.schema_version,
            "timestamp": hc.timestamp,
            "hard_gates_sha256": hc.hard_gates_sha256,
            "kpi_sha256": hc.kpi_sha256,
            "smoke_sha256": hc.smoke_sha256,
            "drill_entries_sha256": hc.drill_entries_sha256,
            "private_staging_sha256": hc.private_staging_sha256,
            "gated_rows_sha256": hc.gated_rows_sha256,
            "final_chain_sha256": hc.final_chain_sha256,
        },
        "gated_rows_artifact": {
            "schema_version": artifact.gated_rows_artifact.schema_version,
            "timestamp": artifact.gated_rows_artifact.timestamp,
            "rows": list(artifact.gated_rows_artifact.rows),
            "required_row_ids": list(
                artifact.gated_rows_artifact.required_row_ids
            ),
            "missing_required_row_ids": list(
                artifact.gated_rows_artifact.missing_required_row_ids
            ),
            "content_sha256": artifact.gated_rows_artifact.content_sha256,
        },
    }


def _format_json(output: P0AcceptanceReportRunOutput) -> str:
    """JSON output (programmatic / audit_events emit 用)."""
    audit_payload = build_p0_acceptance_audit_payload(artifact=output.artifact)
    payload = {
        "report_summary": {
            "p0_exit_decision": output.report.p0_exit_decision,
            "hard_gates_accept": output.report.hard_gates_accept,
            "kpi_accept": output.report.kpi_accept,
            "smoke_success": output.report.smoke_success,
            "host_migration_passed": output.report.host_migration_passed,
            "backup_restore_passed": output.report.backup_restore_passed,
            "private_staging_passed": output.report.private_staging_passed,
            "gated_rows_satisfied": output.report.gated_rows_satisfied,
            "deficiencies": list(output.report.deficiencies),
        },
        "artifact": _artifact_to_dict(output.artifact),
        "audit_payload": audit_payload.to_dict(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _runner_skeleton_response(*, as_json: bool = False) -> tuple[int, str]:
    """skeleton response: 本 batch では input parsing + runner 完成版を別 batch に defer.

    Codex F-PR62-002 P2 adopt: `--json` 指定時は JSON-serializable skeleton
    object を返し、CLI automation (smoke test 等) が stdout を parse 可能.

    実 input JSON deserialization (5 source frozen dataclass の reconstruction)
    は Pydantic schema が必要なため、batch 6.1 で配備. 本 batch では CLI
    structure + help + exit code contract のみ完成.
    """
    if as_json:
        skeleton_payload = {
            "status": "skeleton",
            "batch": "sp012-batch6",
            "next_batch": "batch 6.1 (Pydantic schema input deserialization)",
            "exit_code": 0,
            "next_action": (
                "call run_p0_acceptance_report from Python "
                "(backend.app.services.eval.p0_acceptance_report_runner)"
            ),
            "help_url": (
                "see docs/sprints/SP-012_p0_acceptance.md ## Review batch 6"
            ),
        }
        return 0, json.dumps(skeleton_payload, ensure_ascii=False, indent=2)

    msg = (
        "INFO: Sprint 12 batch 6 — CLI skeleton.\n"
        "Input JSON deserialization (5 source + gated_rows + drill) is\n"
        "configured in batch 6.1 (Pydantic schema needed). To test the\n"
        "runner pipeline today, call run_p0_acceptance_report from Python:\n"
        "  from backend.app.services.eval.p0_acceptance_report_runner import \\\n"
        "      run_p0_acceptance_report\n"
    )
    return 0, msg


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "P0 Acceptance Report CLI (BL-0149): aggregate 7 source + "
            "produce artifact + audit_payload"
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to JSON file with 7 source (batch 6.1+ で full impl)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (default: human-readable text)",
    )
    args = parser.parse_args()

    if args.input is None:
        # skeleton mode: 本 batch では --input なしで help + skeleton info.
        # Codex F-PR62-002 P2 adopt: --json 指定時は JSON skeleton response.
        exit_code, msg = _runner_skeleton_response(as_json=args.json)
        print(msg)  # noqa: T201
        return exit_code

    if not args.input.exists():
        print(f"ERROR: input JSON not found: {args.input}", file=sys.stderr)  # noqa: T201
        return 2

    # batch 6.1+ で Pydantic schema deserialization 配備
    print(  # noqa: T201
        f"ERROR: --input JSON deserialization is implemented in batch 6.1+. "
        f"Current input: {args.input}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
