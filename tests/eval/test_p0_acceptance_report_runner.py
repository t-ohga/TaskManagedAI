"""Sprint 12 batch 6 (BL-0149 evidence chain): runner + audit payload tests."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from backend.app.services.eval.hard_gates_rollup import (
    HardGateEntry,
    HardGatesRollupSummary,
)
from backend.app.services.eval.kpi_rollup import KpiEntry, KpiRollupSummary
from backend.app.services.eval.p0_acceptance_audit_emit import (
    AUDIT_EVENT_TYPE_P0_ACCEPTANCE_REPORT_GENERATED,
    P0AcceptanceAuditPayload,
    build_p0_acceptance_audit_payload,
)
from backend.app.services.eval.p0_acceptance_report import (
    GatedAcceptanceRowEntry,
    GatedRowStatus,
    OperationalDrillEntry,
    OperationalDrillStatus,
    PassEvidence,
    PrivateStagingStatus,
    StructuredDeferFields,
)
from backend.app.services.eval.p0_acceptance_report_runner import (
    P0AcceptanceReportRunnerError,
    P0AcceptanceReportRunOutput,
    run_p0_acceptance_report,
)
from backend.app.services.integration.ticket_to_pr_smoke import (
    SmokeStage,
    SmokeStageResult,
    TicketToPrSmokeResult,
)

_VALID_HASH_A = "a" * 64
_VALID_HASH_B = "b" * 64


def _hard_gates(*, accept: bool = True) -> HardGatesRollupSummary:
    failed = 0 if accept else 1
    entries = tuple(
        HardGateEntry(
            hard_gate_id=hgid,  # type: ignore[arg-type]
            metric_key=key,
            metric_value=1.0,
            threshold_met=(i >= failed),
            threshold_reason="threshold_met" if i >= failed else "below",
        )
        for i, (hgid, key) in enumerate(
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


def _kpi(*, accept: bool = True) -> KpiRollupSummary:
    entries = tuple(
        KpiEntry(
            kpi_id=kid,  # type: ignore[arg-type]
            metric_key=k,
            metric_value=0.9,
            threshold_met=True,
            threshold_reason="threshold_met",
        )
        for kid, k in (
            ("AC-KPI-01", "acceptance_pass_rate"),
            ("AC-KPI-02", "time_to_merge"),
            ("AC-KPI-03", "approval_wait_ms"),
            ("AC-KPI-04", "citation_coverage"),
            ("AC-KPI-05", "cost_per_completed_task"),
        )
    )
    return KpiRollupSummary(
        kpi_count=5,
        met_count=5,
        failed_count=0,
        p0_accept=accept,
        fail_tolerance=1,
        entries=entries,
    )


def _smoke() -> TicketToPrSmokeResult:
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


def _drill(kind: str, *, passed: bool = True) -> OperationalDrillEntry:
    return OperationalDrillEntry(
        drill_kind=kind,
        status=OperationalDrillStatus.PASSED
        if passed
        else OperationalDrillStatus.FAILED,
        completed_at="2026-05-18T01:00:00+00:00",
    )


def test_run_p0_acceptance_report_all_pass_returns_output() -> None:
    """all-pass で runner が report + artifact 両方を返す。"""
    output = run_p0_acceptance_report(
        hard_gates_summary=_hard_gates(accept=True),
        kpi_summary=_kpi(accept=True),
        smoke_result=_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=PrivateStagingStatus.PASSED,
        gated_rows=(),
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T03:00:00+00:00",
    )
    assert isinstance(output, P0AcceptanceReportRunOutput)
    assert output.report.p0_exit_decision is True
    assert output.artifact.p0_exit_decision is True
    assert output.report.deficiencies == ()
    # artifact hash chain は server 計算済
    assert len(output.artifact.hash_chain.final_chain_sha256) == 64


def test_run_p0_acceptance_report_missing_required_row_fails_closed() -> None:
    """required_gated_row_ids non-empty + gated_rows=() で fail-closed。"""
    output = run_p0_acceptance_report(
        hard_gates_summary=_hard_gates(),
        kpi_summary=_kpi(),
        smoke_result=_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=PrivateStagingStatus.PASSED,
        gated_rows=(),
        required_gated_row_ids=frozenset({"BL-0140a-research-to-pr"}),
        timestamp="2026-05-18T03:00:00+00:00",
    )
    assert output.report.p0_exit_decision is False
    assert output.artifact.p0_exit_decision is False
    deficiency_text = " ".join(output.report.deficiencies)
    assert "gated_rows_missing_required" in deficiency_text


def test_run_p0_acceptance_report_drill_kind_mismatch_raises() -> None:
    """drill_kind 違反は ValueError → P0AcceptanceReportRunnerError に変換。"""
    with pytest.raises(P0AcceptanceReportRunnerError, match="generate_p0_acceptance_report failed"):
        run_p0_acceptance_report(
            hard_gates_summary=_hard_gates(),
            kpi_summary=_kpi(),
            smoke_result=_smoke(),
            host_migration_drill=_drill("backup_restore"),  # ← kind mismatch
            backup_restore_drill=_drill("backup_restore"),
            private_staging_status=PrivateStagingStatus.PASSED,
            gated_rows=(),
            required_gated_row_ids=frozenset(),
        )


# === audit emit tests ===


def test_audit_event_type_constant() -> None:
    assert (
        AUDIT_EVENT_TYPE_P0_ACCEPTANCE_REPORT_GENERATED
        == "p0_acceptance_report_generated"
    )


def test_build_audit_payload_includes_final_chain_sha256() -> None:
    """audit payload に final_chain_sha256 + 6 source hash が含まれる。"""
    output = run_p0_acceptance_report(
        hard_gates_summary=_hard_gates(),
        kpi_summary=_kpi(),
        smoke_result=_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=PrivateStagingStatus.PASSED,
        gated_rows=(),
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T03:00:00+00:00",
    )
    payload = build_p0_acceptance_audit_payload(artifact=output.artifact)
    assert isinstance(payload, P0AcceptanceAuditPayload)
    assert payload.p0_exit_decision is True
    assert payload.deficiency_count == 0
    assert payload.deficiency_codes == ()
    # final_chain_sha256 は artifact と一致 (caller verify 可能)
    assert payload.final_chain_sha256 == output.artifact.hash_chain.final_chain_sha256
    # 6 source hash も artifact と一致
    assert payload.gated_rows_sha256 == output.artifact.hash_chain.gated_rows_sha256
    assert payload.hard_gates_sha256 == output.artifact.hash_chain.hard_gates_sha256


def test_audit_payload_deficiency_codes_redacts_raw_values() -> None:
    """deficiency code のみ抽出、raw count / value は含まない (raw secret invariant)."""
    output = run_p0_acceptance_report(
        hard_gates_summary=_hard_gates(accept=False),  # 1 fail
        kpi_summary=_kpi(),
        smoke_result=_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=PrivateStagingStatus.PASSED,
        gated_rows=(),
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T03:00:00+00:00",
    )
    payload = build_p0_acceptance_audit_payload(artifact=output.artifact)
    assert payload.p0_exit_decision is False
    assert payload.deficiency_count > 0
    # code のみで raw value (failed_count=N) は含まない
    for code in payload.deficiency_codes:
        assert "(" not in code  # parens で挟まれた raw value がない
        assert " " not in code  # space で続く詳細値もない


def test_audit_payload_to_dict_json_serializable() -> None:
    """payload.to_dict() で JSON-serializable な dict を返す (DB write 用)。"""
    import json

    output = run_p0_acceptance_report(
        hard_gates_summary=_hard_gates(),
        kpi_summary=_kpi(),
        smoke_result=_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=PrivateStagingStatus.PASSED,
        gated_rows=(),
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T03:00:00+00:00",
    )
    payload = build_p0_acceptance_audit_payload(artifact=output.artifact)
    d = payload.to_dict()
    # JSON serialization 可能
    json_str = json.dumps(d)
    parsed = json.loads(json_str)
    assert parsed["p0_exit_decision"] is True
    assert parsed["schema_version"] == "p0-acceptance/v1"
    assert "deficiency_codes" in parsed


def test_runner_output_frozen() -> None:
    """runner output dataclass は frozen (append-only invariant)."""
    output = run_p0_acceptance_report(
        hard_gates_summary=_hard_gates(),
        kpi_summary=_kpi(),
        smoke_result=_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=PrivateStagingStatus.PASSED,
        gated_rows=(),
        required_gated_row_ids=frozenset(),
    )
    with pytest.raises(AttributeError):
        output.report = None  # type: ignore[misc]


def test_run_with_pass_gated_row_succeeds() -> None:
    """PASS gated row (pass_evidence 必須) を渡しても runner が正常動作。"""
    pass_row = GatedAcceptanceRowEntry(
        row_id="BL-0140a-research-to-pr",
        status=GatedRowStatus.PASS,
        pass_evidence=PassEvidence(
            target_hash=_VALID_HASH_A,
            evidence_artifact_hash=_VALID_HASH_B,
            verified_by="actor:human-1",
            verified_at="2026-05-18T04:00:00+00:00",
        ),
    )
    output = run_p0_acceptance_report(
        hard_gates_summary=_hard_gates(),
        kpi_summary=_kpi(),
        smoke_result=_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=PrivateStagingStatus.PASSED,
        gated_rows=(pass_row,),
        required_gated_row_ids=frozenset({"BL-0140a-research-to-pr"}),
    )
    assert output.report.p0_exit_decision is True
    assert output.report.gated_rows_satisfied is True


def test_sp012_required_gated_row_ids_5_set() -> None:
    """Codex F-PR62-003 P2 partial adopt: SP-012 表 2 由来の 5 必須 row ID set."""
    from backend.app.services.eval.p0_acceptance_report_runner import (
        SP012_REQUIRED_GATED_ROW_IDS,
    )

    assert isinstance(SP012_REQUIRED_GATED_ROW_IDS, frozenset)
    assert len(SP012_REQUIRED_GATED_ROW_IDS) == 5
    assert "BL-0140a-research-to-pr" in SP012_REQUIRED_GATED_ROW_IDS
    assert "AC-KPI-04-research-coverage" in SP012_REQUIRED_GATED_ROW_IDS


def test_runner_synchronizes_timestamp_between_report_and_artifact() -> None:
    """Codex F-PR62-001 P2 adopt: runner で 1 つの timestamp を生成し
    report.timestamp と artifact.timestamp / hash_chain.timestamp が一致する。

    旧設計 (timestamp=None で generate と build が別々に datetime.now()) は
    report と artifact の drift を生む経路 → 物理削除.
    """
    output = run_p0_acceptance_report(
        hard_gates_summary=_hard_gates(),
        kpi_summary=_kpi(),
        smoke_result=_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=PrivateStagingStatus.PASSED,
        gated_rows=(),
        required_gated_row_ids=frozenset(),
        timestamp=None,  # ← runner が自動生成
    )
    # report と artifact の timestamp が同一 (drift なし)
    assert output.report.timestamp == output.artifact.timestamp
    # hash_chain も同 timestamp
    assert output.artifact.hash_chain.timestamp == output.artifact.timestamp
    # gated_rows_artifact も同 timestamp
    assert (
        output.artifact.gated_rows_artifact.timestamp == output.artifact.timestamp
    )


def test_run_with_structured_defer_row_succeeds() -> None:
    """STRUCTURED_DEFER row (6 fields valid) を渡しても runner が正常動作。"""
    deferred_row = GatedAcceptanceRowEntry(
        row_id="BL-other-deferred",
        status=GatedRowStatus.STRUCTURED_DEFER,
        structured_defer_fields=StructuredDeferFields(
            owner="actor:human-1",
            impact="P0 gated",
            resume_condition="condition complete",
            blocked_by=("BL-X",),
            verification="pytest",
            target_hash=_VALID_HASH_A,
        ),
    )
    output = run_p0_acceptance_report(
        hard_gates_summary=_hard_gates(),
        kpi_summary=_kpi(),
        smoke_result=_smoke(),
        host_migration_drill=_drill("host_migration"),
        backup_restore_drill=_drill("backup_restore"),
        private_staging_status=PrivateStagingStatus.PASSED,
        gated_rows=(deferred_row,),
        required_gated_row_ids=frozenset({"BL-other-deferred"}),
    )
    assert output.report.p0_exit_decision is True
    assert output.report.gated_rows_satisfied is True
