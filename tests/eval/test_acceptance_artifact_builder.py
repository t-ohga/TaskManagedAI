"""Sprint 12 batch 5 (BL-0149 prerequisite): AcceptanceArtifactBuilder tests.

server-owned hash + structured_defer 6 fields schema + gated_rows fail-closed の
3 invariants を verify.
"""

from __future__ import annotations

import pytest

from backend.app.services.eval.acceptance_artifact_builder import (
    ARTIFACT_SCHEMA_VERSION,
    AcceptanceHashChain,
    GatedAcceptanceRowsArtifact,
    P0AcceptanceArtifact,
    build_acceptance_hash_chain,
    build_gated_acceptance_rows_artifact,
    build_p0_acceptance_artifact,
)
from backend.app.services.eval.hard_gates_rollup import (
    HardGateEntry,
    HardGatesRollupSummary,
)
from backend.app.services.eval.kpi_rollup import KpiEntry, KpiRollupSummary
from backend.app.services.eval.p0_acceptance_report import (
    GatedAcceptanceRowEntry,
    GatedRowStatus,
    OperationalDrillEntry,
    OperationalDrillStatus,
    P0AcceptanceReportSummary,
    PrivateStagingStatus,
    StructuredDeferFields,
)
from backend.app.services.integration.ticket_to_pr_smoke import (
    SmokeStage,
    SmokeStageResult,
    TicketToPrSmokeResult,
)


def _valid_structured_defer() -> StructuredDeferFields:
    return StructuredDeferFields(
        owner="actor:human-1",
        impact="P0 core acceptance gated",
        resume_condition="BL-X complete",
        blocked_by=("BL-X",),
        verification="pytest",
        target_hash="sha256:abcdef0123456789",
    )


def _build_report_all_pass() -> P0AcceptanceReportSummary:
    """all-pass P0 report fixture (drill_entries / private_staging も passed)."""
    from types import MappingProxyType

    hg_entries = tuple(
        HardGateEntry(
            hard_gate_id=hgid,  # type: ignore[arg-type]
            metric_key=key,
            metric_value=1.0,
            threshold_met=True,
            threshold_reason="threshold_met",
        )
        for hgid, key in (
            ("AC-HARD-01", "policy_block_recall"),
            ("AC-HARD-02", "secret_canary_no_leak"),
            ("AC-HARD-03", "tenant_isolation_negative_pass"),
            ("AC-HARD-04", "backup_restore_rpo_rto"),
            ("AC-HARD-05", "forbidden_path_block"),
            ("AC-HARD-06", "dangerous_command_block"),
            ("AC-HARD-07", "prompt_injection_resist"),
        )
    )
    hg = HardGatesRollupSummary(
        hard_gate_count=7,
        met_count=7,
        failed_count=0,
        p0_accept=True,
        fail_tolerance=0,
        entries=hg_entries,
    )
    kpi_entries = tuple(
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
    kpi = KpiRollupSummary(
        kpi_count=5,
        met_count=5,
        failed_count=0,
        p0_accept=True,
        fail_tolerance=1,
        entries=kpi_entries,
    )
    smoke_stages = tuple(
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
    smoke = TicketToPrSmokeResult(
        stage_count=6,
        succeeded_count=6,
        failed_count=0,
        skipped_count=0,
        overall_success=True,
        stages=smoke_stages,
    )
    host_drill = OperationalDrillEntry(
        drill_kind="host_migration",
        status=OperationalDrillStatus.PASSED,
        completed_at="2026-05-18T01:00:00+00:00",
    )
    backup_drill = OperationalDrillEntry(
        drill_kind="backup_restore",
        status=OperationalDrillStatus.PASSED,
        completed_at="2026-05-18T02:00:00+00:00",
    )
    return P0AcceptanceReportSummary(
        timestamp="2026-05-18T03:00:00+00:00",
        hard_gates_accept=True,
        kpi_accept=True,
        smoke_success=True,
        host_migration_passed=True,
        backup_restore_passed=True,
        private_staging_passed=True,
        gated_rows_satisfied=True,
        p0_exit_decision=True,
        hard_gates_summary=hg,
        kpi_summary=kpi,
        smoke_result=smoke,
        drill_entries=(host_drill, backup_drill),
        private_staging_status=PrivateStagingStatus.PASSED,
        gated_rows=(),
        deficiencies=(),
    )


def test_build_gated_rows_artifact_empty_required_empty_provided() -> None:
    """required + provided 共に空 → artifact 生成成功、missing なし。"""
    artifact = build_gated_acceptance_rows_artifact(
        gated_rows=(),
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T00:00:00+00:00",
    )
    assert isinstance(artifact, GatedAcceptanceRowsArtifact)
    assert artifact.schema_version == ARTIFACT_SCHEMA_VERSION
    assert artifact.rows == ()
    assert artifact.required_row_ids == ()
    assert artifact.missing_required_row_ids == ()
    assert len(artifact.content_sha256) == 64  # SHA-256 hex


def test_build_gated_rows_artifact_records_missing_required() -> None:
    """required に含まれるが provided にない row は missing_required_row_ids に記録。"""
    artifact = build_gated_acceptance_rows_artifact(
        gated_rows=(),
        required_gated_row_ids=frozenset({"BL-A", "BL-B"}),
        timestamp="2026-05-18T00:00:00+00:00",
    )
    assert artifact.missing_required_row_ids == ("BL-A", "BL-B")  # sorted
    assert artifact.required_row_ids == ("BL-A", "BL-B")


def test_build_gated_rows_artifact_with_structured_defer_persists_6_fields() -> None:
    """STRUCTURED_DEFER row の 6 fields が artifact rows に永続化される。"""
    row = GatedAcceptanceRowEntry(
        row_id="BL-X",
        status=GatedRowStatus.STRUCTURED_DEFER,
        structured_defer_fields=_valid_structured_defer(),
    )
    artifact = build_gated_acceptance_rows_artifact(
        gated_rows=(row,),
        required_gated_row_ids=frozenset({"BL-X"}),
        timestamp="2026-05-18T00:00:00+00:00",
    )
    assert len(artifact.rows) == 1
    sd_dict = artifact.rows[0]["structured_defer_fields"]
    assert sd_dict is not None
    assert sd_dict["owner"] == "actor:human-1"
    assert sd_dict["blocked_by"] == ["BL-X"]  # tuple → list (JSON)
    assert artifact.rows[0]["structured_defer_fields_present"] is True
    assert artifact.rows[0]["missing_fields"] == []


def test_build_gated_rows_artifact_content_sha256_deterministic() -> None:
    """同じ input + 同じ timestamp で content_sha256 が決定的 (RFC 8785 canonical)."""
    args = {
        "gated_rows": (),
        "required_gated_row_ids": frozenset({"BL-X"}),
        "timestamp": "2026-05-18T00:00:00+00:00",
    }
    a1 = build_gated_acceptance_rows_artifact(**args)
    a2 = build_gated_acceptance_rows_artifact(**args)
    assert a1.content_sha256 == a2.content_sha256


def test_build_gated_rows_artifact_content_sha256_changes_with_input() -> None:
    """input が異なれば content_sha256 が変わる (改ざん detect)."""
    a1 = build_gated_acceptance_rows_artifact(
        gated_rows=(),
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T00:00:00+00:00",
    )
    a2 = build_gated_acceptance_rows_artifact(
        gated_rows=(),
        required_gated_row_ids=frozenset({"BL-X"}),  # 差分
        timestamp="2026-05-18T00:00:00+00:00",
    )
    assert a1.content_sha256 != a2.content_sha256


def test_build_acceptance_hash_chain_all_6_hashes_present() -> None:
    """hash chain は 6 source + final_chain の 7 hash を持つ。"""
    report = _build_report_all_pass()
    rows_artifact = build_gated_acceptance_rows_artifact(
        gated_rows=(),
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T03:00:00+00:00",
    )
    chain = build_acceptance_hash_chain(
        report=report,
        gated_rows_artifact=rows_artifact,
        timestamp="2026-05-18T03:00:00+00:00",
    )
    assert isinstance(chain, AcceptanceHashChain)
    for h in (
        chain.hard_gates_sha256,
        chain.kpi_sha256,
        chain.smoke_sha256,
        chain.drill_entries_sha256,
        chain.private_staging_sha256,
        chain.gated_rows_sha256,
        chain.final_chain_sha256,
    ):
        assert len(h) == 64  # SHA-256 hex
    # gated_rows_sha256 は rows_artifact.content_sha256 と一致 (caller hash 経路なし)
    assert chain.gated_rows_sha256 == rows_artifact.content_sha256


def test_build_acceptance_hash_chain_deterministic() -> None:
    """同じ report + rows_artifact + timestamp で chain が決定的。"""
    report = _build_report_all_pass()
    rows_artifact = build_gated_acceptance_rows_artifact(
        gated_rows=(),
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T03:00:00+00:00",
    )
    c1 = build_acceptance_hash_chain(
        report=report,
        gated_rows_artifact=rows_artifact,
        timestamp="2026-05-18T03:00:00+00:00",
    )
    c2 = build_acceptance_hash_chain(
        report=report,
        gated_rows_artifact=rows_artifact,
        timestamp="2026-05-18T03:00:00+00:00",
    )
    assert c1.final_chain_sha256 == c2.final_chain_sha256


def test_build_p0_acceptance_artifact_all_components_present() -> None:
    """end-to-end: build_p0_acceptance_artifact が rows_artifact + hash_chain を含む。"""
    report = _build_report_all_pass()
    artifact = build_p0_acceptance_artifact(
        report=report,
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T03:00:00+00:00",
    )
    assert isinstance(artifact, P0AcceptanceArtifact)
    assert artifact.schema_version == ARTIFACT_SCHEMA_VERSION
    assert artifact.p0_exit_decision is True
    assert artifact.deficiencies == ()
    assert artifact.gated_rows_artifact.content_sha256 == (
        artifact.hash_chain.gated_rows_sha256
    )


def test_build_p0_acceptance_artifact_records_deficiencies_from_report() -> None:
    """report.deficiencies が artifact に保存される (audit truth)."""
    from dataclasses import replace

    base = _build_report_all_pass()
    failed_report = replace(
        base,
        p0_exit_decision=False,
        hard_gates_accept=False,
        deficiencies=("hard_gates_failed (test fixture)",),
    )
    artifact = build_p0_acceptance_artifact(
        report=failed_report,
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T03:00:00+00:00",
    )
    assert artifact.p0_exit_decision is False
    assert artifact.deficiencies == ("hard_gates_failed (test fixture)",)


def test_artifact_is_frozen_dataclass() -> None:
    """全 artifact dataclass は frozen (append-only invariant)。"""
    artifact = build_gated_acceptance_rows_artifact(
        gated_rows=(),
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T00:00:00+00:00",
    )
    with pytest.raises(AttributeError):
        artifact.content_sha256 = "tampered"  # type: ignore[misc]
