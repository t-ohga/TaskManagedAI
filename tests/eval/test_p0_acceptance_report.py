"""Sprint 12 batch 4 (BL-0149): P0 Acceptance Report generator tests.

5 source (Hard Gates + KPI + smoke + host_migration + backup_restore) を
mock duck-typed object で構築 → generate_p0_acceptance_report → P0 Exit
verdict + deficiency reasons を verify.

Anti-Gaming: 5 source 全件 PASS で True、1 source でも未達なら False.
drill_status=deferred_user_confirm は **未達** として扱う (Hard Gates と同 invariant).
"""

from __future__ import annotations

import pytest

from backend.app.services.eval.hard_gates_rollup import (
    HardGateEntry,
    HardGatesRollupSummary,
)
from backend.app.services.eval.kpi_rollup import KpiEntry, KpiRollupSummary
from backend.app.services.eval.p0_acceptance_report import (
    REQUIRED_DRILLS,
    GatedAcceptanceRowEntry,
    GatedRowStatus,
    OperationalDrillEntry,
    OperationalDrillStatus,
    P0AcceptanceReportSummary,
    PrivateStagingStatus,
    generate_p0_acceptance_report,
)
from backend.app.services.integration.ticket_to_pr_smoke import (
    SmokeStage,
    SmokeStageResult,
    TicketToPrSmokeResult,
)


def _build_hard_gates(*, accept: bool = True) -> HardGatesRollupSummary:
    """Hard Gates summary fixture (default = all-pass)."""

    failed = 0 if accept else 1
    entries = tuple(
        HardGateEntry(
            hard_gate_id=hard_gate_id,  # type: ignore[arg-type]
            metric_key=metric_key,
            metric_value=1.0,
            threshold_met=(i >= failed),  # 1 件 fail なら first 1 件
            threshold_reason="threshold_met" if i >= failed else "below_threshold",
        )
        for i, (hard_gate_id, metric_key) in enumerate(
            (
                ("AC-HARD-01", "policy_block_recall"),
                ("AC-HARD-02", "secret_canary_no_leak"),
                ("AC-HARD-03", "tenant_isolation_negative_pass"),
                ("AC-HARD-04", "backup_restore_rpo_rto"),
                ("AC-HARD-05", "forbidden_path_block"),
                ("AC-HARD-06", "dangerous_command_block"),
                ("AC-HARD-07", "prompt_injection_resist"),
            )
        )
    )
    return HardGatesRollupSummary(
        hard_gate_count=7,
        met_count=7 - failed,
        failed_count=failed,
        p0_accept=accept,
        fail_tolerance=0,
        entries=entries,
    )


def _build_kpi(*, accept: bool = True) -> KpiRollupSummary:
    """KPI summary fixture (default = all-pass)."""

    failed = 0 if accept else 2  # 2 件 fail で kpi_accept=False (tolerance=1)
    entries = tuple(
        KpiEntry(
            kpi_id=kpi_id,  # type: ignore[arg-type]
            metric_key=metric_key,
            metric_value=0.9,
            threshold_met=(i >= failed),
            threshold_reason="threshold_met" if i >= failed else "below_threshold",
        )
        for i, (kpi_id, metric_key) in enumerate(
            (
                ("AC-KPI-01", "acceptance_pass_rate"),
                ("AC-KPI-02", "time_to_merge"),
                ("AC-KPI-03", "approval_wait_ms"),
                ("AC-KPI-04", "citation_coverage"),
                ("AC-KPI-05", "cost_per_completed_task"),
            )
        )
    )
    return KpiRollupSummary(
        kpi_count=5,
        met_count=5 - failed,
        failed_count=failed,
        p0_accept=accept,
        fail_tolerance=1,
        entries=entries,
    )


def _build_smoke(*, success: bool = True) -> TicketToPrSmokeResult:
    """Smoke result fixture (default = all-succeeded)."""

    from types import MappingProxyType

    if success:
        stages = tuple(
            SmokeStageResult(
                stage=stage,
                status="succeeded",
                duration_ms=10,
                metadata=MappingProxyType({}),
            )
            for stage in (
                SmokeStage.TICKET,
                SmokeStage.RUN,
                SmokeStage.APPROVE,
                SmokeStage.REPO,
                SmokeStage.EVAL,
                SmokeStage.AUDIT,
            )
        )
        return TicketToPrSmokeResult(
            stage_count=6,
            succeeded_count=6,
            failed_count=0,
            skipped_count=0,
            overall_success=True,
            stages=stages,
        )
    # 1 stage fail (APPROVE)、AUDIT は実行される (Codex F-PR58-002 P1 invariant)
    stages = tuple(
        SmokeStageResult(
            stage=stage,
            status=(
                "succeeded"
                if stage in (SmokeStage.TICKET, SmokeStage.RUN, SmokeStage.AUDIT)
                else "failed"
                if stage is SmokeStage.APPROVE
                else "skipped"
            ),
            duration_ms=10,
            error_code=None if stage is not SmokeStage.APPROVE else "stage_failed",
            error_summary=None if stage is not SmokeStage.APPROVE else "test failure",
            metadata=MappingProxyType({}),
        )
        for stage in (
            SmokeStage.TICKET,
            SmokeStage.RUN,
            SmokeStage.APPROVE,
            SmokeStage.REPO,
            SmokeStage.EVAL,
            SmokeStage.AUDIT,
        )
    )
    return TicketToPrSmokeResult(
        stage_count=6,
        succeeded_count=3,
        failed_count=1,
        skipped_count=2,
        overall_success=False,
        stages=stages,
    )


def _drill(
    kind: str, status: OperationalDrillStatus = OperationalDrillStatus.PASSED
) -> OperationalDrillEntry:
    # Codex F-PR60-001 P1 adopt: PASSED/FAILED 時は completed_at 必須
    completed_at = (
        "2026-05-17T12:00:00+00:00"
        if status in (OperationalDrillStatus.PASSED, OperationalDrillStatus.FAILED)
        else None
    )
    return OperationalDrillEntry(
        drill_kind=kind, status=status, completed_at=completed_at
    )


def _staging_passed() -> PrivateStagingStatus:
    return PrivateStagingStatus.PASSED


def _gated_rows_all_pass() -> tuple[GatedAcceptanceRowEntry, ...]:
    """gated rows 0 件 (Sprint 12 P0 core では gated row 未定義のため empty で all-pass)。"""
    return ()

def _required_gated_row_ids_empty() -> frozenset[str]:
    """required_gated_row_ids 空 (gated_rows も空で all-pass 経路、本 fixture
    の Sprint 12 P0 core 想定: 必須 row なし)。"""
    return frozenset()



def test_required_drills_immutable() -> None:
    """REQUIRED_DRILLS は固定順序 (Anti-Gaming、reorder 禁止)."""
    assert REQUIRED_DRILLS == ("host_migration", "backup_restore")


def test_all_pass_p0_exit_true() -> None:
    """5 source 全件 PASS → p0_exit_decision=True、deficiencies 空."""
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=True),
        kpi_summary=_build_kpi(accept=True),
        smoke_result=_build_smoke(success=True),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert isinstance(report, P0AcceptanceReportSummary)
    assert report.hard_gates_accept is True
    assert report.kpi_accept is True
    assert report.smoke_success is True
    assert report.host_migration_passed is True
    assert report.backup_restore_passed is True
    assert report.p0_exit_decision is True
    assert report.deficiencies == ()


def test_hard_gates_fail_p0_exit_false() -> None:
    """Hard Gates 1 件 fail → p0_exit_decision=False、deficiencies に hard_gates_failed."""
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=False),
        kpi_summary=_build_kpi(accept=True),
        smoke_result=_build_smoke(success=True),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert report.p0_exit_decision is False
    assert any("hard_gates_failed" in d for d in report.deficiencies)


def test_kpi_fail_p0_exit_false() -> None:
    """KPI 2 件 fail → p0_exit_decision=False、deficiencies に kpi_failed."""
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=True),
        kpi_summary=_build_kpi(accept=False),
        smoke_result=_build_smoke(success=True),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert report.p0_exit_decision is False
    assert any("kpi_failed" in d for d in report.deficiencies)


def test_smoke_fail_p0_exit_false() -> None:
    """smoke fail → p0_exit_decision=False、deficiencies に smoke_failed."""
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=True),
        kpi_summary=_build_kpi(accept=True),
        smoke_result=_build_smoke(success=False),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert report.p0_exit_decision is False
    assert any("smoke_failed" in d for d in report.deficiencies)


def test_host_migration_deferred_p0_exit_false() -> None:
    """host migration drill が deferred_user_confirm → p0_exit_decision=False。

    Anti-Gaming: drill 未実行 (defer 状態) を pass にしない invariant.
    """
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=True),
        kpi_summary=_build_kpi(accept=True),
        smoke_result=_build_smoke(success=True),
        host_migration_drill=_drill(
            "host_migration", OperationalDrillStatus.DEFERRED_USER_CONFIRM
        ),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert report.host_migration_passed is False
    assert report.p0_exit_decision is False
    assert any(
        "host_migration_drill_not_passed" in d for d in report.deficiencies
    )


def test_backup_restore_failed_p0_exit_false() -> None:
    """backup_restore drill が failed → p0_exit_decision=False。"""
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=True),
        kpi_summary=_build_kpi(accept=True),
        smoke_result=_build_smoke(success=True),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill(
            "backup_restore", OperationalDrillStatus.FAILED
        ),
        private_staging_status=_staging_passed(),
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert report.backup_restore_passed is False
    assert report.p0_exit_decision is False
    assert any(
        "backup_restore_drill_not_passed" in d for d in report.deficiencies
    )


def test_drill_kind_mismatch_raises_value_error() -> None:
    """drill_kind の field 整合性違反は ValueError raise (contract 保護)."""
    with pytest.raises(ValueError, match="host_migration_drill.drill_kind must be"):
        generate_p0_acceptance_report(
            hard_gates_summary=_build_hard_gates(),
            kpi_summary=_build_kpi(),
            smoke_result=_build_smoke(),
            host_migration_drill=_drill("backup_restore"),  # 逆指定
            backup_restore_drill=_drill("backup_restore"),
            private_staging_status=_staging_passed(),
            gated_rows=_gated_rows_all_pass(),
            required_gated_row_ids=_required_gated_row_ids_empty(),
        )


def test_drill_kind_mismatch_backup_raises_value_error() -> None:
    """backup_restore_drill 側の kind mismatch も verify."""
    with pytest.raises(ValueError, match="backup_restore_drill.drill_kind must be"):
        generate_p0_acceptance_report(
            hard_gates_summary=_build_hard_gates(),
            kpi_summary=_build_kpi(),
            smoke_result=_build_smoke(),
            host_migration_drill=_drill("host_migration"),
            backup_restore_drill=_drill("host_migration"),  # 逆指定
            private_staging_status=_staging_passed(),
            gated_rows=_gated_rows_all_pass(),
            required_gated_row_ids=_required_gated_row_ids_empty(),
        )


def test_all_fail_returns_all_deficiencies() -> None:
    """7 source 全件未達 → 7 deficiency reasons 全件記録 (Codex F-PR60-002/003 P1 反映)."""
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=False),
        kpi_summary=_build_kpi(accept=False),
        smoke_result=_build_smoke(success=False),
        host_migration_drill=_drill(
            "host_migration", OperationalDrillStatus.FAILED
        ),
        backup_restore_drill=_drill(
            "backup_restore", OperationalDrillStatus.FAILED
        ),
        private_staging_status=PrivateStagingStatus.FAILED,
        gated_rows=(
            GatedAcceptanceRowEntry(
                row_id="test_row",
                status=GatedRowStatus.MISSING,
            ),
        ),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert report.p0_exit_decision is False
    # 5 source (Hard Gates + KPI + smoke + 2 drill) + private_staging + gated_rows = 7 deficiency
    assert len(report.deficiencies) == 7
    deficiency_text = " ".join(report.deficiencies)
    assert "hard_gates_failed" in deficiency_text
    assert "kpi_failed" in deficiency_text
    assert "smoke_failed" in deficiency_text
    assert "host_migration_drill_not_passed" in deficiency_text
    assert "private_staging_not_passed" in deficiency_text
    assert "gated_rows_unsatisfied" in deficiency_text
    assert "backup_restore_drill_not_passed" in deficiency_text


def test_drill_status_enum_values() -> None:
    """OperationalDrillStatus enum 5 値 verify (Anti-Gaming、append-only)."""
    assert OperationalDrillStatus.PENDING == "pending"
    assert OperationalDrillStatus.IN_PROGRESS == "in_progress"
    assert OperationalDrillStatus.PASSED == "passed"
    assert OperationalDrillStatus.FAILED == "failed"
    assert OperationalDrillStatus.DEFERRED_USER_CONFIRM == "deferred_user_confirm"


def test_drill_entries_include_both_drills() -> None:
    """drill_entries は (host_migration, backup_restore) 順で記録."""
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(),
        kpi_summary=_build_kpi(),
        smoke_result=_build_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert len(report.drill_entries) == 2
    assert report.drill_entries[0].drill_kind == "host_migration"
    assert report.drill_entries[1].drill_kind == "backup_restore"


def test_report_is_frozen_dataclass() -> None:
    """P0AcceptanceReportSummary は frozen + append-only invariant."""
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(),
        kpi_summary=_build_kpi(),
        smoke_result=_build_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    with pytest.raises(AttributeError):
        report.p0_exit_decision = False  # type: ignore[misc]
    with pytest.raises(AttributeError):
        report.drill_entries[0].status = OperationalDrillStatus.FAILED  # type: ignore[misc]


def test_timestamp_override() -> None:
    """timestamp は caller が ISO 8601 string で override 可能."""
    fixed_ts = "2026-05-17T12:34:56+00:00"
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(),
        kpi_summary=_build_kpi(),
        smoke_result=_build_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        timestamp=fixed_ts,
        private_staging_status=_staging_passed(),
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert report.timestamp == fixed_ts


def test_default_timestamp_is_utc_iso() -> None:
    """default timestamp は ISO 8601 UTC format。"""
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(),
        kpi_summary=_build_kpi(),
        smoke_result=_build_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    # ISO 8601 + tz suffix (+00:00) を含む
    assert "T" in report.timestamp
    assert "+00:00" in report.timestamp


def test_drill_passed_without_completed_at_raises_value_error() -> None:
    """Codex F-PR60-001 P1 adopt: PASSED 状態は completed_at 必須。"""
    with pytest.raises(
        ValueError, match="completed_at is required when status is PASSED"
    ):
        OperationalDrillEntry(
            drill_kind="host_migration",
            status=OperationalDrillStatus.PASSED,
            completed_at=None,  # 未指定で PASSED は不可
        )


def test_drill_failed_without_completed_at_raises_value_error() -> None:
    """Codex F-PR60-001 P1 adopt: FAILED 状態も completed_at 必須。"""
    with pytest.raises(
        ValueError, match="completed_at is required when status is PASSED"
    ):
        OperationalDrillEntry(
            drill_kind="backup_restore",
            status=OperationalDrillStatus.FAILED,
            completed_at=None,
        )


def test_drill_pending_allows_no_completed_at() -> None:
    """Codex F-PR60-001 P1 adopt: PENDING / IN_PROGRESS / DEFERRED は completed_at 不要。"""
    # 例外なしで生成可能
    entry = OperationalDrillEntry(
        drill_kind="host_migration",
        status=OperationalDrillStatus.PENDING,
        completed_at=None,
    )
    assert entry.completed_at is None


def test_private_staging_not_passed_p0_exit_false() -> None:
    """Codex F-PR60-002 P1 adopt: private staging が PASSED 以外なら P0 未達。"""
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=True),
        kpi_summary=_build_kpi(accept=True),
        smoke_result=_build_smoke(success=True),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=PrivateStagingStatus.NOT_RUN,
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert report.private_staging_passed is False
    assert report.p0_exit_decision is False
    assert any("private_staging_not_passed" in d for d in report.deficiencies)


def test_gated_row_natural_defer_p0_exit_false() -> None:
    """Codex F-PR60-003 P1 adopt: NATURAL_DEFER (自然文 defer) は P0 未達。"""
    rows = (
        GatedAcceptanceRowEntry(
            row_id="BL-0140a-research-to-pr",
            status=GatedRowStatus.NATURAL_DEFER,
        ),
    )
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=True),
        kpi_summary=_build_kpi(accept=True),
        smoke_result=_build_smoke(success=True),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=rows,
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert report.gated_rows_satisfied is False
    assert report.p0_exit_decision is False


def test_gated_row_structured_defer_with_fields_p0_exit_true() -> None:
    """Codex F-PR60-003 P1 adopt: STRUCTURED_DEFER + 6 fields full は P0 OK。"""
    from backend.app.services.eval.p0_acceptance_report import (
        StructuredDeferFields,
    )

    rows = (
        GatedAcceptanceRowEntry(
            row_id="BL-0140a-research-to-pr",
            status=GatedRowStatus.STRUCTURED_DEFER,
            structured_defer_fields=StructuredDeferFields(
                owner="actor:human-1",
                impact="P0 core acceptance gated",
                resume_condition="BL-0140a complete",
                blocked_by=("BL-0140a",),
                verification="pytest tests/integration/test_research_to_pr.py",
                target_hash="abc123def456",
            ),
        ),
    )
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=True),
        kpi_summary=_build_kpi(accept=True),
        smoke_result=_build_smoke(success=True),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=rows,
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert report.gated_rows_satisfied is True
    assert report.p0_exit_decision is True


def test_gated_row_structured_defer_without_fields_p0_exit_false() -> None:
    """STRUCTURED_DEFER だが 6 fields schema 未満は未達。"""
    from backend.app.services.eval.p0_acceptance_report import (
        StructuredDeferFields,
    )

    rows = (
        GatedAcceptanceRowEntry(
            row_id="BL-0140a-research-to-pr",
            status=GatedRowStatus.STRUCTURED_DEFER,
            structured_defer_fields=StructuredDeferFields(
                owner="actor:human-1",
                impact="P0 core acceptance gated",
                resume_condition="",  # ← 空文字 = schema 不備
                blocked_by=("BL-0140a",),
                verification="pytest",
                target_hash="abc123",
            ),
        ),
    )
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=True),
        kpi_summary=_build_kpi(accept=True),
        smoke_result=_build_smoke(success=True),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=rows,
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert report.gated_rows_satisfied is False
    assert report.p0_exit_decision is False


def test_inconsistent_hard_gates_summary_rejected() -> None:
    """Codex F-PR60-004 P2 adopt: stale/inconsistent summary を recompute で reject.

    p0_accept=True だが failed_count > tolerance な不整合 summary を渡しても、
    aggregator が entries から recompute し False に戻す.
    """
    # 不整合 summary: p0_accept=True だが entries は 1 件 fail
    failed_entry = HardGateEntry(
        hard_gate_id="AC-HARD-01",
        metric_key="policy_block_recall",
        metric_value=0.5,
        threshold_met=False,  # ← 失敗
        threshold_reason="below_threshold",
    )
    other_entries = tuple(
        HardGateEntry(
            hard_gate_id=hgid,  # type: ignore[arg-type]
            metric_key=key,
            metric_value=1.0,
            threshold_met=True,
            threshold_reason="threshold_met",
        )
        for hgid, key in (
            ("AC-HARD-02", "secret_canary_no_leak"),
            ("AC-HARD-03", "tenant_isolation_negative_pass"),
            ("AC-HARD-04", "backup_restore_rpo_rto"),
            ("AC-HARD-05", "forbidden_path_block"),
            ("AC-HARD-06", "dangerous_command_block"),
            ("AC-HARD-07", "prompt_injection_resist"),
        )
    )
    inconsistent_summary = HardGatesRollupSummary(
        hard_gate_count=7,
        met_count=7,  # ← 誤った count (本当は 6)
        failed_count=0,  # ← 誤った count (本当は 1)
        p0_accept=True,  # ← inconsistent boolean
        fail_tolerance=0,
        entries=(failed_entry,) + other_entries,
    )
    report = generate_p0_acceptance_report(
        hard_gates_summary=inconsistent_summary,
        kpi_summary=_build_kpi(accept=True),
        smoke_result=_build_smoke(success=True),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    # recompute で 1 件 fail を検出、hard_gates_accept=False、deficiency に inconsistent_summary
    assert report.hard_gates_accept is False
    assert report.p0_exit_decision is False
    deficiency_text = " ".join(report.deficiencies)
    assert "hard_gates_inconsistent_summary" in deficiency_text


def test_empty_gated_rows_with_required_ids_fails_closed() -> None:
    """Codex 監査 F-AUDIT-001 P1 adopt: required_gated_row_ids が non-empty で
    gated_rows=() (空) なら p0_exit_decision=False (Anti-Gaming 違反を物理削除)。

    旧設計 (gated_rows=() で all() が True を返す) は SP-012 line 87-99 違反.
    """
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=True),
        kpi_summary=_build_kpi(accept=True),
        smoke_result=_build_smoke(success=True),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=(),  # 空 (旧設計では all-pass 経路)
        required_gated_row_ids=frozenset({"BL-0140a-research-to-pr"}),
    )
    assert report.gated_rows_satisfied is False
    assert report.p0_exit_decision is False
    deficiency_text = " ".join(report.deficiencies)
    assert "gated_rows_missing_required" in deficiency_text
    assert "BL-0140a-research-to-pr" in deficiency_text


def test_partial_gated_rows_with_required_ids_fails_closed() -> None:
    """required_gated_row_ids の一部しか提供されていない → fail-closed。"""
    from backend.app.services.eval.p0_acceptance_report import (
        StructuredDeferFields,
    )

    rows = (
        GatedAcceptanceRowEntry(
            row_id="BL-0140a-research-to-pr",
            status=GatedRowStatus.STRUCTURED_DEFER,
            structured_defer_fields=StructuredDeferFields(
                owner="actor:human",
                impact="impact",
                resume_condition="cond",
                blocked_by=("BL-X",),
                verification="verify",
                target_hash="hash",
            ),
        ),
    )
    report = generate_p0_acceptance_report(
        hard_gates_summary=_build_hard_gates(accept=True),
        kpi_summary=_build_kpi(accept=True),
        smoke_result=_build_smoke(success=True),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=rows,
        required_gated_row_ids=frozenset(
            {"BL-0140a-research-to-pr", "BL-OTHER-required"}
        ),  # BL-OTHER-required が missing
    )
    assert report.gated_rows_satisfied is False
    assert report.p0_exit_decision is False
    deficiency_text = " ".join(report.deficiencies)
    assert "BL-OTHER-required" in deficiency_text


def test_structured_defer_fields_schema_invalid_raises_via_property() -> None:
    """structured_defer_fields に空 field を渡すと is_schema_valid()=False、
    GatedAcceptanceRowEntry.structured_defer_fields_present=False になる。"""
    from backend.app.services.eval.p0_acceptance_report import (
        StructuredDeferFields,
    )

    invalid_fields = StructuredDeferFields(
        owner="actor:human",
        impact="impact",
        resume_condition="cond",
        blocked_by=(),  # ← 空 list = schema-invalid
        verification="verify",
        target_hash="hash",
    )
    row = GatedAcceptanceRowEntry(
        row_id="BL-x",
        status=GatedRowStatus.STRUCTURED_DEFER,
        structured_defer_fields=invalid_fields,
    )
    assert row.structured_defer_fields_present is False
    assert "blocked_by" in invalid_fields.missing_fields()


def test_structured_defer_status_without_fields_raises_value_error() -> None:
    """status=STRUCTURED_DEFER で structured_defer_fields=None は contract 違反。"""
    with pytest.raises(
        ValueError, match="structured_defer_fields is required"
    ):
        GatedAcceptanceRowEntry(
            row_id="BL-x",
            status=GatedRowStatus.STRUCTURED_DEFER,
            structured_defer_fields=None,
        )


def test_structured_defer_all_6_fields_full_passes() -> None:
    """6 fields full + non-empty なら is_schema_valid()=True、
    GatedAcceptanceRowEntry.structured_defer_fields_present=True。"""
    from backend.app.services.eval.p0_acceptance_report import (
        StructuredDeferFields,
    )

    valid_fields = StructuredDeferFields(
        owner="actor:human-1",
        impact="acceptance gated",
        resume_condition="BL-Y complete",
        blocked_by=("BL-Y", "ADR-00099"),
        verification="pytest tests/foo",
        target_hash="sha256:abc",
    )
    assert valid_fields.is_schema_valid() is True
    assert valid_fields.missing_fields() == ()

    row = GatedAcceptanceRowEntry(
        row_id="BL-Y",
        status=GatedRowStatus.STRUCTURED_DEFER,
        structured_defer_fields=valid_fields,
    )
    assert row.structured_defer_fields_present is True


def test_summaries_accessible_in_report() -> None:
    """report は集約元 summaries を保持し audit / drill-down 可能。"""
    hg = _build_hard_gates(accept=True)
    kpi = _build_kpi(accept=True)
    smoke = _build_smoke(success=True)
    report = generate_p0_acceptance_report(
        hard_gates_summary=hg,
        kpi_summary=kpi,
        smoke_result=smoke,
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=_staging_passed(),
        gated_rows=_gated_rows_all_pass(),
        required_gated_row_ids=_required_gated_row_ids_empty(),
    )
    assert report.hard_gates_summary is hg
    assert report.kpi_summary is kpi
    assert report.smoke_result is smoke
