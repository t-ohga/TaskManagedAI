"""Sprint 12 batch 6 (BL-0149 evidence chain): P0 acceptance report runner.

高レベル runner: caller (CLI / API endpoint) から呼ばれ、5 source rollup
(Hard Gates / KPI / smoke / drill / private_staging) + gated_rows + required
ID set を受け、`P0AcceptanceArtifact` を返す.

設計:
- runner は pure (no DB / network、acceptance_artifact_builder と
  generate_p0_acceptance_report の組み合わせ)
- caller が drill entries / private_staging / gated_rows を組み立てる経路 (drill は
  user 物理確認、private_staging は GitHub Actions、gated_rows は BL-0140a 完成)
- API / CLI / audit_events emit は本 runner の output を消費するだけ

Anti-Gaming:
- runner は report + artifact 2 つを sync で返し、caller が hash chain final を
  audit に記録する責務 (本 module は raw secret を含まない)
- raw secret / capability token は input にも output にも含まれない
- `required_gated_row_ids` は本 module の caller (CLI / endpoint) が決定
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from backend.app.services.eval.acceptance_artifact_builder import (
    P0AcceptanceArtifact,
    build_p0_acceptance_artifact,
)
from backend.app.services.eval.hard_gates_rollup import HardGatesRollupSummary
from backend.app.services.eval.kpi_rollup import KpiRollupSummary
from backend.app.services.eval.p0_acceptance_report import (
    GatedAcceptanceRowEntry,
    OperationalDrillEntry,
    P0AcceptanceReportSummary,
    PrivateStagingStatus,
    generate_p0_acceptance_report,
)
from backend.app.services.integration.ticket_to_pr_smoke import (
    TicketToPrSmokeResult,
)

# Codex F-PR62-003 P2 partial adopt: SP-012 line 87-99 表 2 由来の必須
# gated row ID set (server-owned spec)。caller (CLI / endpoint / BL-0149
# sign-off step) は本 constant を default で渡せる. batch 7+ で server-owned
# spec loader (eval/acceptance/sp012_gated_rows.json 等) を配備すれば
# 本 constant を loader 経由で derive 可能.
#
# SP-012 line 91-98 由来:
# - BL-0140a Research-to-PR gold flow
# - AC-KPI-04 Research path verify
# - agent_runs.parent_run_id cross-project negative (BL-0029b)
# - research_tasks cross-project negative (BL-0029c)
# - secret_capability_tokens.agent_run_id FK Research binding (BL-0151b)
SP012_REQUIRED_GATED_ROW_IDS: Final[frozenset[str]] = frozenset(
    {
        "BL-0140a-research-to-pr",
        "AC-KPI-04-research-coverage",
        "BL-0029b-agent_runs-parent_run_id-cross-project",
        "BL-0029c-research_tasks-cross-project",
        "BL-0151b-secret_capability_tokens-agent_run_id-research-binding",
    }
)


class P0AcceptanceReportRunnerError(RuntimeError):
    """P0 acceptance report runner failure."""


@dataclass(frozen=True, slots=True)
class P0AcceptanceReportRunOutput:
    """Runner output: report + artifact (frozen、caller が emit / persist 担当)."""

    report: P0AcceptanceReportSummary
    artifact: P0AcceptanceArtifact


def run_p0_acceptance_report(
    *,
    hard_gates_summary: HardGatesRollupSummary,
    kpi_summary: KpiRollupSummary,
    smoke_result: TicketToPrSmokeResult,
    host_migration_drill: OperationalDrillEntry,
    backup_restore_drill: OperationalDrillEntry,
    private_staging_status: PrivateStagingStatus,
    gated_rows: tuple[GatedAcceptanceRowEntry, ...],
    required_gated_row_ids: frozenset[str],
    timestamp: str | None = None,
) -> P0AcceptanceReportRunOutput:
    """7 source の report + artifact を pure に生成 (caller-supplied 経路なし).

    Args:
        hard_gates_summary: HardGatesRollupSummary (caller が事前 evaluate)
        kpi_summary: KpiRollupSummary (caller が事前 evaluate)
        smoke_result: TicketToPrSmokeResult (BL-0140b smoke gold flow run 後)
        host_migration_drill: real drill 実行 後の entry
        backup_restore_drill: real drill 実行 後の entry
        private_staging_status: GitHub Actions run 後の status
        gated_rows: BL-0140a Research-to-PR + 他 gated row の entries
        required_gated_row_ids: SP-012 表 2 由来の必須 row ID set
        timestamp: artifact 生成時刻 (default = now UTC)

    Returns:
        report (verdict + deficiencies) + artifact (hash chain + persistence dict).

    Note (Codex F-PR62-003 defer): `required_gated_row_ids` を空 frozenset で
    渡すと、Sprint 12 P0 core (gated row 不在の場合) で all-pass する経路は
    残っている。SP-012 表 2 由来の server-owned spec loader (gated rows 必須
    set) は **batch 7+ で配備予定**。本 runner は caller (CLI / endpoint /
    audit emit step) が `required_gated_row_ids` を渡す責務とし、empty が
    意図的か誤入力かは caller 側で判断する設計 (BL-0140a の structured_defer 6
    fields 永続化が完成するまでは empty が valid な P0 core 経路).
    """

    # Codex F-PR62-001 P2 adopt: report と artifact の timestamp drift を物理削除.
    # caller が timestamp を指定しない場合、runner で 1 つ生成して両方に渡す.
    effective_timestamp = timestamp or datetime.now(tz=UTC).isoformat()

    try:
        report = generate_p0_acceptance_report(
            hard_gates_summary=hard_gates_summary,
            kpi_summary=kpi_summary,
            smoke_result=smoke_result,
            host_migration_drill=host_migration_drill,
            backup_restore_drill=backup_restore_drill,
            private_staging_status=private_staging_status,
            gated_rows=gated_rows,
            required_gated_row_ids=required_gated_row_ids,
            timestamp=effective_timestamp,
        )
    except ValueError as exc:
        raise P0AcceptanceReportRunnerError(
            f"generate_p0_acceptance_report failed: {exc}"
        ) from exc

    try:
        artifact = build_p0_acceptance_artifact(
            report=report,
            required_gated_row_ids=required_gated_row_ids,
            timestamp=effective_timestamp,
        )
    except ValueError as exc:
        raise P0AcceptanceReportRunnerError(
            f"build_p0_acceptance_artifact failed: {exc}"
        ) from exc

    return P0AcceptanceReportRunOutput(report=report, artifact=artifact)


__all__ = [
    "SP012_REQUIRED_GATED_ROW_IDS",
    "P0AcceptanceReportRunOutput",
    "P0AcceptanceReportRunnerError",
    "run_p0_acceptance_report",
]
