"""Sprint 12 batch 4 (BL-0149): P0 Acceptance Report generator.

P0 Exit sign-off の最終判定 + evidence chain artifact 生成 pure function.

PRD-01 / 計画(仮).md / .claude/reference/hard-gates-and-kpis.md による P0 Exit:
1. Hard Gates 7 全件達成 (`hard_gates.p0_accept == True`、fail_tolerance=0)
2. Quality KPIs 5 のうち未達 1 個以下 (`kpi.p0_accept == True`、fail_tolerance=1)
3. Ticket-to-PR smoke gold flow 通し (`smoke.overall_success == True`)
4. host migration drill (Mac → VPS、ADR-00021) — **user 物理確認必要、本 batch では defer**
5. backup/restore drill (RPO ≤ 24h、RTO ≤ 4h、PITR 成功) — **user 物理確認必要、本 batch では defer**

本 module は (1)-(3) の集約と P0 Exit verdict を pure function で計算し、
(4)-(5) は `OperationalDrillStatus` で **drill_status enum** (pending /
in_progress / passed / failed / deferred_user_confirm) として記録する.
real drill の実行・記録は user 確認後の別 batch / 別 session で配備.

Anti-Gaming invariant:
- P0 Exit decision は 5 source (HARD + KPI + smoke + host_migration + backup_restore)
  全件 PASS で True、1 source でも未達なら False
- drill_status=deferred_user_confirm は **未達** として扱う (Hard Gates と同 invariant)
- caller-supplied 経路なし (signature 上 inputs 固定)
- frozen dataclass (event sourcing 整合、append-only)

Security boundary:
- pure function (no DB / FS / network access)
- raw secret は input に含まれない (caller が redaction 済 summary を渡す)
- evidence chain hash (kpi_rollup + smoke + hard_gates) は caller が compute (本 batch では shape のみ確立)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from backend.app.services.eval.hard_gates_rollup import HardGatesRollupSummary
from backend.app.services.eval.kpi_rollup import KpiRollupSummary
from backend.app.services.integration.ticket_to_pr_smoke import (
    TicketToPrSmokeResult,
)


class OperationalDrillStatus(StrEnum):
    """Operational drill (host migration / backup restore) status enum.

    P0 Exit gate で AC-HARD-04 backup_restore_rpo_rto / host migration drill の
    実 run 結果を記録. real drill は user 物理確認必要、本 batch では
    `deferred_user_confirm` を default として扱い、別 session で `passed` / `failed`
    に上書きする経路.
    """

    PENDING = "pending"  # drill 未着手
    IN_PROGRESS = "in_progress"  # 実行中
    PASSED = "passed"  # 成功 (RPO ≤ 24h / RTO ≤ 4h verified)
    FAILED = "failed"  # 失敗 (criteria 未達)
    DEFERRED_USER_CONFIRM = "deferred_user_confirm"  # user 物理確認待ち (本 batch default)


# P0 Exit に required な drill 種別 (固定 enum、reorder 禁止)
REQUIRED_DRILLS: Final[tuple[str, ...]] = (
    "host_migration",
    "backup_restore",
)


@dataclass(frozen=True, slots=True)
class OperationalDrillEntry:
    """単一 drill の status entry (frozen、append-only)."""

    drill_kind: str  # "host_migration" / "backup_restore"
    status: OperationalDrillStatus
    completed_at: str | None = None  # ISO 8601 (passed/failed 時のみ非 None)
    notes: str | None = None  # redaction 済 summary (caller responsibility)


@dataclass(frozen=True, slots=True)
class P0AcceptanceReportSummary:
    """P0 Exit final report (frozen、append-only audit truth)."""

    timestamp: str  # ISO 8601 UTC、report 生成時刻
    # 5 sources の P0 判定状態
    hard_gates_accept: bool  # HardGatesRollupSummary.p0_accept
    kpi_accept: bool  # KpiRollupSummary.p0_accept
    smoke_success: bool  # TicketToPrSmokeResult.overall_success
    host_migration_passed: bool  # drill_status == passed
    backup_restore_passed: bool  # drill_status == passed
    # 最終 verdict (5 source 全件 PASS で True、1 source でも未達なら False)
    p0_exit_decision: bool
    # 集計詳細 (audit / report 出力用)
    hard_gates_summary: HardGatesRollupSummary
    kpi_summary: KpiRollupSummary
    smoke_result: TicketToPrSmokeResult
    drill_entries: tuple[OperationalDrillEntry, ...]
    # P0 未達時の reason codes (verdict=False 時のみ非空)
    deficiencies: tuple[str, ...]


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def generate_p0_acceptance_report(
    *,
    hard_gates_summary: HardGatesRollupSummary,
    kpi_summary: KpiRollupSummary,
    smoke_result: TicketToPrSmokeResult,
    host_migration_drill: OperationalDrillEntry,
    backup_restore_drill: OperationalDrillEntry,
    timestamp: str | None = None,
) -> P0AcceptanceReportSummary:
    """5 source の P0 判定結果を集約し、最終 P0 Exit verdict を計算する pure function.

    Args:
        hard_gates_summary: Hard Gates 7 rollup result
        kpi_summary: KPI 5 rollup result
        smoke_result: Ticket-to-PR smoke gold flow result
        host_migration_drill: host migration drill status
        backup_restore_drill: backup/restore drill status
        timestamp: report 生成時刻 (default = now UTC ISO 8601)

    Returns:
        P0AcceptanceReportSummary with p0_exit_decision + deficiency reasons.
    """

    # drill kind 整合 verify (signature 固定だが contract 保護)
    if host_migration_drill.drill_kind != "host_migration":
        raise ValueError(
            f"host_migration_drill.drill_kind must be 'host_migration', "
            f"got {host_migration_drill.drill_kind!r}"
        )
    if backup_restore_drill.drill_kind != "backup_restore":
        raise ValueError(
            f"backup_restore_drill.drill_kind must be 'backup_restore', "
            f"got {backup_restore_drill.drill_kind!r}"
        )

    host_migration_passed = (
        host_migration_drill.status == OperationalDrillStatus.PASSED
    )
    backup_restore_passed = (
        backup_restore_drill.status == OperationalDrillStatus.PASSED
    )

    # 5 source 全件 PASS で P0 Exit OK
    p0_exit_decision = (
        hard_gates_summary.p0_accept
        and kpi_summary.p0_accept
        and smoke_result.overall_success
        and host_migration_passed
        and backup_restore_passed
    )

    # deficiency reasons (verdict=False 時の audit)
    deficiencies: list[str] = []
    if not hard_gates_summary.p0_accept:
        deficiencies.append(
            f"hard_gates_failed (failed_count={hard_gates_summary.failed_count}/7, "
            f"fail_tolerance=0)"
        )
    if not kpi_summary.p0_accept:
        deficiencies.append(
            f"kpi_failed (failed_count={kpi_summary.failed_count}/5, "
            f"fail_tolerance=1)"
        )
    if not smoke_result.overall_success:
        deficiencies.append(
            f"smoke_failed (failed_count={smoke_result.failed_count}, "
            f"skipped_count={smoke_result.skipped_count})"
        )
    if not host_migration_passed:
        deficiencies.append(
            f"host_migration_drill_not_passed "
            f"(status={host_migration_drill.status})"
        )
    if not backup_restore_passed:
        deficiencies.append(
            f"backup_restore_drill_not_passed "
            f"(status={backup_restore_drill.status})"
        )

    return P0AcceptanceReportSummary(
        timestamp=timestamp or _now_utc_iso(),
        hard_gates_accept=hard_gates_summary.p0_accept,
        kpi_accept=kpi_summary.p0_accept,
        smoke_success=smoke_result.overall_success,
        host_migration_passed=host_migration_passed,
        backup_restore_passed=backup_restore_passed,
        p0_exit_decision=p0_exit_decision,
        hard_gates_summary=hard_gates_summary,
        kpi_summary=kpi_summary,
        smoke_result=smoke_result,
        drill_entries=(host_migration_drill, backup_restore_drill),
        deficiencies=tuple(deficiencies),
    )


__all__ = [
    "REQUIRED_DRILLS",
    "OperationalDrillEntry",
    "OperationalDrillStatus",
    "P0AcceptanceReportSummary",
    "generate_p0_acceptance_report",
]
