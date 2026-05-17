"""Sprint 12 batch 4 (BL-0149): P0 Acceptance Report generator.

P0 Exit sign-off の最終判定 + evidence chain artifact 生成 pure function.

PRD-01 / 計画(仮).md / .claude/reference/hard-gates-and-kpis.md による P0 Exit:
1. Hard Gates 7 全件達成 (`hard_gates.p0_accept == True`、fail_tolerance=0)
2. Quality KPIs 5 のうち未達 1 個以下 (`kpi.p0_accept == True`、fail_tolerance=1)
3. Ticket-to-PR smoke gold flow 通し (`smoke.overall_success == True`)
4. host migration drill — **user 物理確認必要、本 batch では defer**
5. backup/restore drill — **user 物理確認必要、本 batch では defer**
6. **private staging CI/E2E 完成** (SP-012 line 82 must_ship、Codex F-PR60-002 P1 adopt)
7. **gated_acceptance_rows 全件 PASS or schema-valid STRUCTURED_DEFER**
   (SP-012 line 89 invariant、Codex F-PR60-003 P1 adopt、Research-to-PR 等)

本 module は (1)-(3) の集約 + (4)-(7) の status 入力 + 最終 verdict を pure
function で計算. real drill / staging / row 実行は別 session で配備.

Anti-Gaming invariant:
- P0 Exit decision は **7 source** 全件 PASS で True、1 source でも未達なら False
- drill_status=deferred_user_confirm は未達として扱う (Hard Gates と同 invariant)
- private_staging_status=not_run も未達 (Codex F-PR60-002 P1)
- gated_row が schema-invalid な defer or missing は未達 (Codex F-PR60-003 P1)
- Codex F-PR60-001 P1: drill.PASSED/FAILED は completed_at 非 None 必須
- Codex F-PR60-004 P2: rollup summary integrity check (boolean を直接 trust せず recompute)
- caller-supplied 経路なし (signature 上 inputs 固定)
- frozen dataclass (event sourcing 整合、append-only)

Security boundary:
- pure function (no DB / FS / network access)
- raw secret は input に含まれない (caller が redaction 済 summary を渡す)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from backend.app.services.eval.hard_gates_rollup import (
    HARD_GATE_FAIL_TOLERANCE,
    HardGatesRollupSummary,
)
from backend.app.services.eval.kpi_rollup import (
    KPI_FAIL_TOLERANCE,
    KpiRollupSummary,
)
from backend.app.services.integration.ticket_to_pr_smoke import (
    TicketToPrSmokeResult,
)


class OperationalDrillStatus(StrEnum):
    """Operational drill (host migration / backup restore) status enum."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    DEFERRED_USER_CONFIRM = "deferred_user_confirm"


class PrivateStagingStatus(StrEnum):
    """Private staging CI/E2E status enum (Codex F-PR60-002 P1).

    SP-012 line 82 must_ship: private staging CI/E2E 完成. PASSED 以外は P0 未達.
    """

    NOT_RUN = "not_run"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    DEFERRED_USER_CONFIRM = "deferred_user_confirm"


class GatedRowStatus(StrEnum):
    """Gated acceptance row status enum (Codex F-PR60-003 P1).

    SP-012 line 89 invariant: BL-0149 sign-off は各 gated row が PASS、または
    `STRUCTURED_DEFER` (6 fields full: owner / impact / resume_condition /
    blocked_by / verification / target_hash) でなければ BLOCK. それ以外
    (NATURAL_DEFER, MISSING) は未達.
    """

    PASS = "pass"  # noqa: S105 (P0 acceptance enum value, not a password)
    STRUCTURED_DEFER = "structured_defer"  # 6 fields schema-valid
    NATURAL_DEFER = "natural_defer"  # 自然文 defer (不可、P0 未達)
    MISSING = "missing"  # 未記録 (P0 未達)


REQUIRED_DRILLS: Final[tuple[str, ...]] = (
    "host_migration",
    "backup_restore",
)


@dataclass(frozen=True, slots=True)
class OperationalDrillEntry:
    """単一 drill の status entry (frozen、append-only).

    Codex F-PR60-001 P1 adopt: status=PASSED/FAILED 時に completed_at が
    None なら invalid (`__post_init__` で ValueError raise).
    """

    drill_kind: str
    status: OperationalDrillStatus
    completed_at: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        # Codex F-PR60-001 P1 adopt: drill completion evidence 必須
        # (PASSED/FAILED 状態は ISO 8601 timestamp 必須、bare status を許さない)
        if self.status in (
            OperationalDrillStatus.PASSED,
            OperationalDrillStatus.FAILED,
        ) and not self.completed_at:
            raise ValueError(
                f"OperationalDrillEntry(drill_kind={self.drill_kind!r}, "
                f"status={self.status}): completed_at is required when "
                f"status is PASSED or FAILED (Codex F-PR60-001 P1 invariant)"
            )


@dataclass(frozen=True, slots=True)
class GatedAcceptanceRowEntry:
    """gated_acceptance_rows artifact の 1 row (frozen)."""

    row_id: str  # SP-012 spec の "BL-0140a-research-to-pr" 等
    status: GatedRowStatus
    structured_defer_fields_present: bool = False  # 6 fields schema-valid 時 True


@dataclass(frozen=True, slots=True)
class P0AcceptanceReportSummary:
    """P0 Exit final report (frozen、append-only audit truth)."""

    timestamp: str
    # 7 sources の P0 判定状態
    hard_gates_accept: bool
    kpi_accept: bool
    smoke_success: bool
    host_migration_passed: bool
    backup_restore_passed: bool
    private_staging_passed: bool  # Codex F-PR60-002 P1
    gated_rows_satisfied: bool  # Codex F-PR60-003 P1
    # 最終 verdict (7 source 全件 PASS で True)
    p0_exit_decision: bool
    # 集計詳細
    hard_gates_summary: HardGatesRollupSummary
    kpi_summary: KpiRollupSummary
    smoke_result: TicketToPrSmokeResult
    drill_entries: tuple[OperationalDrillEntry, ...]
    private_staging_status: PrivateStagingStatus
    gated_rows: tuple[GatedAcceptanceRowEntry, ...]
    deficiencies: tuple[str, ...]


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _recompute_hard_gates_accept(summary: HardGatesRollupSummary) -> bool:
    """Codex F-PR60-004 P2 adopt: rollup summary を trust せず entries から recompute.

    `p0_accept=True` だが `failed_count > fail_tolerance` 等の inconsistent
    summary を reject. entries の `threshold_met AND metric_value is not None`
    で met を再計算し、`failed_count <= fail_tolerance` で判定.
    """
    recomputed_met = sum(
        1 for e in summary.entries if e.threshold_met and e.metric_value is not None
    )
    recomputed_failed = len(summary.entries) - recomputed_met
    return recomputed_failed <= HARD_GATE_FAIL_TOLERANCE


def _recompute_kpi_accept(summary: KpiRollupSummary) -> bool:
    """Codex F-PR60-004 P2 adopt: KPI rollup summary を trust せず recompute."""
    recomputed_met = sum(
        1 for e in summary.entries if e.threshold_met and e.metric_value is not None
    )
    recomputed_failed = len(summary.entries) - recomputed_met
    return recomputed_failed <= KPI_FAIL_TOLERANCE


def generate_p0_acceptance_report(
    *,
    hard_gates_summary: HardGatesRollupSummary,
    kpi_summary: KpiRollupSummary,
    smoke_result: TicketToPrSmokeResult,
    host_migration_drill: OperationalDrillEntry,
    backup_restore_drill: OperationalDrillEntry,
    private_staging_status: PrivateStagingStatus,
    gated_rows: tuple[GatedAcceptanceRowEntry, ...],
    timestamp: str | None = None,
) -> P0AcceptanceReportSummary:
    """7 source の P0 判定結果を集約し、最終 P0 Exit verdict を計算する pure function.

    Codex PR #60 R1 P1×3 + P2×1 adopt: 5 source → 7 source へ拡張、
    drill completion evidence 必須化、rollup recompute integrity check.
    """

    # drill kind 整合 verify
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

    # Codex F-PR60-004 P2 adopt: rollup summary integrity recompute
    hard_gates_accept = _recompute_hard_gates_accept(hard_gates_summary)
    kpi_accept = _recompute_kpi_accept(kpi_summary)

    host_migration_passed = (
        host_migration_drill.status == OperationalDrillStatus.PASSED
    )
    backup_restore_passed = (
        backup_restore_drill.status == OperationalDrillStatus.PASSED
    )

    # Codex F-PR60-002 P1 adopt: private staging も P0 verdict に必須
    private_staging_passed = private_staging_status == PrivateStagingStatus.PASSED

    # Codex F-PR60-003 P1 adopt: gated rows は PASS or STRUCTURED_DEFER のみ許容
    # (NATURAL_DEFER / MISSING は P0 未達). row が 0 件の場合は許容 (caller
    # が gated rows を採用しない場合の経路、SP-012 表 2 entry なしの worst case).
    gated_rows_satisfied = all(
        row.status == GatedRowStatus.PASS
        or (
            row.status == GatedRowStatus.STRUCTURED_DEFER
            and row.structured_defer_fields_present
        )
        for row in gated_rows
    )

    # 7 source 全件 PASS で P0 Exit OK
    p0_exit_decision = (
        hard_gates_accept
        and kpi_accept
        and smoke_result.overall_success
        and host_migration_passed
        and backup_restore_passed
        and private_staging_passed
        and gated_rows_satisfied
    )

    # deficiency reasons
    deficiencies: list[str] = []
    if not hard_gates_accept:
        # recompute と original p0_accept の不整合も明示
        if hard_gates_summary.p0_accept:
            deficiencies.append(
                "hard_gates_inconsistent_summary "
                "(p0_accept=True but recomputed_failed > tolerance)"
            )
        deficiencies.append(
            f"hard_gates_failed (failed_count={hard_gates_summary.failed_count}/"
            f"{hard_gates_summary.hard_gate_count}, fail_tolerance="
            f"{HARD_GATE_FAIL_TOLERANCE})"
        )
    if not kpi_accept:
        if kpi_summary.p0_accept:
            deficiencies.append(
                "kpi_inconsistent_summary "
                "(p0_accept=True but recomputed_failed > tolerance)"
            )
        deficiencies.append(
            f"kpi_failed (failed_count={kpi_summary.failed_count}/"
            f"{kpi_summary.kpi_count}, fail_tolerance={KPI_FAIL_TOLERANCE})"
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
    if not private_staging_passed:
        deficiencies.append(
            f"private_staging_not_passed (status={private_staging_status})"
        )
    if not gated_rows_satisfied:
        unsatisfied = [
            r.row_id
            for r in gated_rows
            if r.status not in (GatedRowStatus.PASS,)
            and not (
                r.status == GatedRowStatus.STRUCTURED_DEFER
                and r.structured_defer_fields_present
            )
        ]
        deficiencies.append(
            f"gated_rows_unsatisfied (rows={unsatisfied})"
        )

    return P0AcceptanceReportSummary(
        timestamp=timestamp or _now_utc_iso(),
        hard_gates_accept=hard_gates_accept,
        kpi_accept=kpi_accept,
        smoke_success=smoke_result.overall_success,
        host_migration_passed=host_migration_passed,
        backup_restore_passed=backup_restore_passed,
        private_staging_passed=private_staging_passed,
        gated_rows_satisfied=gated_rows_satisfied,
        p0_exit_decision=p0_exit_decision,
        hard_gates_summary=hard_gates_summary,
        kpi_summary=kpi_summary,
        smoke_result=smoke_result,
        drill_entries=(host_migration_drill, backup_restore_drill),
        private_staging_status=private_staging_status,
        gated_rows=gated_rows,
        deficiencies=tuple(deficiencies),
    )


__all__ = [
    "REQUIRED_DRILLS",
    "GatedAcceptanceRowEntry",
    "GatedRowStatus",
    "OperationalDrillEntry",
    "OperationalDrillStatus",
    "P0AcceptanceReportSummary",
    "PrivateStagingStatus",
    "generate_p0_acceptance_report",
]
