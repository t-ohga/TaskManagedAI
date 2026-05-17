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

import re
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

# Codex F-PR61-004 P1 adopt: target_hash / evidence_artifact_hash は SHA-256
# hex (64 chars lowercase) 必須。"todo" / placeholder text を schema-valid
# として扱わない invariant.
_SHA256_HEX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-f0-9]{64}$")


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


# Codex 監査 (2026-05-18) F-AUDIT-002 P1 adopt: structured_defer 6 fields は
# SP-012 line 218-247 で永続化 + schema 検査が必須。caller が bool flag を
# 自由に渡せる経路を物理削除し、6 fields の実値から server-owned に判定.
_STRUCTURED_DEFER_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "owner",
    "impact",
    "resume_condition",
    "blocked_by",
    "verification",
    "target_hash",
)


@dataclass(frozen=True, slots=True)
class StructuredDeferFields:
    """SP-012 line 218-247 structured_defer 6 fields schema (frozen).

    Codex 監査 (2026-05-18) F-AUDIT-002 P1 adopt: 6 fields full + non-empty が
    schema-valid invariant. 1 field でも欠落 / 空文字 / blocked_by 空 list なら
    schema-invalid として fail-closed.
    """

    owner: str  # gated row owner actor_id
    impact: str  # P0 acceptance への impact 説明
    resume_condition: str  # 完了条件
    blocked_by: tuple[str, ...]  # 阻害要因 (BL ID / external dep / ADR)
    verification: str  # verify 方法
    target_hash: str  # acceptance artifact hash (server-computed)

    def is_schema_valid(self) -> bool:
        """6 fields 全件 non-empty + target_hash が SHA-256 hex (64 chars) なら True.

        Codex F-PR61-004 P1 adopt: target_hash が placeholder text (例: "todo")
        で schema-valid と扱われる経路を物理削除。SP-012 line 218-247 invariant
        として target_hash は acceptance artifact の SHA-256 (server-verified).
        """
        return (
            bool(self.owner.strip())
            and bool(self.impact.strip())
            and bool(self.resume_condition.strip())
            and len(self.blocked_by) > 0
            and bool(self.verification.strip())
            and self._is_valid_target_hash()
        )

    def _is_valid_target_hash(self) -> bool:
        """target_hash が SHA-256 hex (lowercase 64 chars) かを正規表現で検査."""
        stripped = self.target_hash.strip()
        return bool(stripped) and _SHA256_HEX_PATTERN.match(stripped) is not None

    def missing_fields(self) -> tuple[str, ...]:
        """schema-invalid な fields の名前 tuple (audit / deficiency 用).

        Codex F-PR61-004 P1 adopt: target_hash が hex 形式でなければ
        "target_hash_not_sha256_hex" として記録 (placeholder "todo" 等の検知).
        """
        missing: list[str] = []
        if not self.owner.strip():
            missing.append("owner")
        if not self.impact.strip():
            missing.append("impact")
        if not self.resume_condition.strip():
            missing.append("resume_condition")
        if len(self.blocked_by) == 0:
            missing.append("blocked_by")
        if not self.verification.strip():
            missing.append("verification")
        if not self.target_hash.strip():
            missing.append("target_hash")
        elif not self._is_valid_target_hash():
            missing.append("target_hash_not_sha256_hex")
        return tuple(missing)


@dataclass(frozen=True, slots=True)
class PassEvidence:
    """gated row が PASS の時に必須な evidence (frozen).

    Codex F-PR61-005 P2 adopt: PASS row も target_hash / evidence_artifact_hash /
    verified_by / verified_at を持ち、persisted artifact の改ざん detect を
    可能にする invariant. evidence_artifact_hash と target_hash は SHA-256 hex.
    """

    target_hash: str  # acceptance target artifact の SHA-256 hex (64 chars)
    evidence_artifact_hash: str  # evidence artifact (e.g. PR diff) の SHA-256 hex
    verified_by: str  # 検証 actor_id (human + service 両方許容)
    verified_at: str  # ISO 8601 UTC

    def __post_init__(self) -> None:
        """contract: target_hash / evidence_artifact_hash は SHA-256 hex 必須."""
        if not _SHA256_HEX_PATTERN.match(self.target_hash.strip()):
            raise ValueError(
                f"PassEvidence.target_hash must be SHA-256 hex (64 chars), "
                f"got {self.target_hash!r}"
            )
        if not _SHA256_HEX_PATTERN.match(self.evidence_artifact_hash.strip()):
            raise ValueError(
                f"PassEvidence.evidence_artifact_hash must be SHA-256 hex, "
                f"got {self.evidence_artifact_hash!r}"
            )
        if not self.verified_by.strip():
            raise ValueError("PassEvidence.verified_by must be non-empty")
        if not self.verified_at.strip():
            raise ValueError("PassEvidence.verified_at must be non-empty")


@dataclass(frozen=True, slots=True)
class GatedAcceptanceRowEntry:
    """gated_acceptance_rows artifact の 1 row (frozen).

    Codex 監査 (2026-05-18) F-AUDIT-002 P1 adopt: status=STRUCTURED_DEFER 時は
    `structured_defer_fields` 必須 + 6 fields schema-valid 必須.
    `structured_defer_fields_present` boolean は server 側で
    `structured_defer_fields.is_schema_valid()` から自動算出.

    Codex F-PR61-005 P2 adopt: status=PASS 時は `pass_evidence` 必須 (PASS row も
    target_hash / evidence_artifact_hash / verified_by / verified_at を持ち、
    persisted artifact 改ざん detect を可能にする).
    """

    row_id: str  # SP-012 spec の "BL-0140a-research-to-pr" 等
    status: GatedRowStatus
    structured_defer_fields: StructuredDeferFields | None = None  # STRUCTURED_DEFER 時必須
    pass_evidence: PassEvidence | None = None  # PASS 時必須 (F-PR61-005)

    def __post_init__(self) -> None:
        """contract: STRUCTURED_DEFER は structured_defer_fields 必須、PASS は pass_evidence 必須."""
        if (
            self.status == GatedRowStatus.STRUCTURED_DEFER
            and self.structured_defer_fields is None
        ):
            raise ValueError(
                f"GatedAcceptanceRowEntry(row_id={self.row_id!r}, "
                f"status=STRUCTURED_DEFER): structured_defer_fields is required "
                f"(SP-012 line 218-247 invariant)"
            )
        if (
            self.status == GatedRowStatus.PASS
            and self.pass_evidence is None
        ):
            raise ValueError(
                f"GatedAcceptanceRowEntry(row_id={self.row_id!r}, "
                f"status=PASS): pass_evidence is required (Codex F-PR61-005 P2 "
                f"adopt: PASS row must carry tamper-evident evidence)"
            )

    @property
    def structured_defer_fields_present(self) -> bool:
        """structured_defer_fields が 6 fields schema-valid なら True."""
        return (
            self.structured_defer_fields is not None
            and self.structured_defer_fields.is_schema_valid()
        )


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
    required_gated_row_ids: frozenset[str],
    timestamp: str | None = None,
) -> P0AcceptanceReportSummary:
    """7 source の P0 判定結果を集約し、最終 P0 Exit verdict を計算する pure function.

    Codex PR #60 R1 P1×3 + P2×1 adopt: 5 source → 7 source へ拡張、
    drill completion evidence 必須化、rollup recompute integrity check.

    Codex 監査 (2026-05-18) F-AUDIT-001 P1 adopt: `required_gated_row_ids` を
    必須引数化。SP-012 表 2 line 87-99 invariant「P0 Exit sign-off は各 gated
    row が PASS or schema-valid STRUCTURED_DEFER でなければ BLOCK」を server
    側で enforce。caller が `gated_rows=()` (空 tuple) を渡しても、
    `required_gated_row_ids` が non-empty なら all-pass にならない (Anti-Gaming
    defense-in-depth、empty=all-pass の経路を物理削除).
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

    # Codex 監査 (2026-05-18) F-AUDIT-001 P1 adopt: gated rows fail-closed
    # invariant の強化。次の 3 条件全て満たす場合のみ gated_rows_satisfied=True:
    # (1) `required_gated_row_ids` 全件が gated_rows に含まれる (missing 排除)
    # (2) gated_rows 内の各 row が PASS または schema-valid STRUCTURED_DEFER
    # (3) extraneous row (required に無い id) は warning のみ (排除しない、
    #     SP-012 表 2 拡張の経路を残す)
    #
    # 旧設計 (gated_rows=() で all() が True) は Anti-Gaming 違反のため
    # 物理削除. `required_gated_row_ids` が non-empty なら、empty/incomplete
    # gated_rows は確実に未達.
    provided_row_ids = {row.row_id for row in gated_rows}
    missing_required_row_ids = required_gated_row_ids - provided_row_ids
    rows_satisfied_per_entry = [
        row.status == GatedRowStatus.PASS
        or (
            row.status == GatedRowStatus.STRUCTURED_DEFER
            and row.structured_defer_fields_present
        )
        for row in gated_rows
    ]
    gated_rows_satisfied = (
        len(missing_required_row_ids) == 0
        and all(rows_satisfied_per_entry)
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
        # Codex 監査 (2026-05-18) F-AUDIT-001 P1 adopt: missing required row と
        # status-unsatisfied row を別々に deficiency 記録 (audit truth).
        if missing_required_row_ids:
            deficiencies.append(
                f"gated_rows_missing_required "
                f"(missing={sorted(missing_required_row_ids)})"
            )
        unsatisfied = [
            r.row_id
            for r in gated_rows
            if r.status not in (GatedRowStatus.PASS,)
            and not (
                r.status == GatedRowStatus.STRUCTURED_DEFER
                and r.structured_defer_fields_present
            )
        ]
        if unsatisfied:
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
    "STRUCTURED_DEFER_REQUIRED_FIELDS",
    "GatedAcceptanceRowEntry",
    "GatedRowStatus",
    "OperationalDrillEntry",
    "OperationalDrillStatus",
    "P0AcceptanceReportSummary",
    "PassEvidence",
    "PrivateStagingStatus",
    "StructuredDeferFields",
    "generate_p0_acceptance_report",
]

# 公開エイリアス: AcceptanceArtifactBuilder や caller test で参照する。
STRUCTURED_DEFER_REQUIRED_FIELDS = _STRUCTURED_DEFER_REQUIRED_FIELDS
