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
        target_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
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


def test_build_p0_artifact_overrides_decision_when_builder_detects_missing() -> None:
    """Codex F-PR61-001 P1 adopt: report.p0_exit_decision=True でも builder で
    missing required row 検出時に decision=False に override + deficiency 追加。
    """
    base = _build_report_all_pass()
    # report は all-pass だが、required_gated_row_ids に新 row を追加して
    # builder 側で missing を検出させる
    artifact = build_p0_acceptance_artifact(
        report=base,
        required_gated_row_ids=frozenset({"BL-NEW-required-by-builder"}),
        timestamp="2026-05-18T03:00:00+00:00",
    )
    assert artifact.p0_exit_decision is False  # builder で override
    deficiency_text = " ".join(artifact.deficiencies)
    assert "gated_rows_missing_required_in_builder" in deficiency_text
    assert "BL-NEW-required-by-builder" in deficiency_text


def test_canonical_hash_nfc_normalize() -> None:
    """Codex F-PR61-003 P2 adopt: NFD vs NFC で同じ意味の文字列で同 hash。

    decomposed (NFD) と precomposed (NFC) で同じ意味の Unicode 文字列を
    含む StructuredDeferFields owner で同じ hash が出る invariant.
    """
    from backend.app.services.eval.p0_acceptance_report import (
        StructuredDeferFields,
    )

    # "é" = U+00E9 (NFC) vs "é" = U+0065 U+0301 (NFD、e + combining acute)
    valid_hash = "a" * 64
    nfc_owner = "actor:Caféé"  # precomposed
    nfd_owner = "actor:Caféé"  # decomposed

    row_nfc = GatedAcceptanceRowEntry(
        row_id="BL-X",
        status=GatedRowStatus.STRUCTURED_DEFER,
        structured_defer_fields=StructuredDeferFields(
            owner=nfc_owner,
            impact="i",
            resume_condition="r",
            blocked_by=("B",),
            verification="v",
            target_hash=valid_hash,
        ),
    )
    row_nfd = GatedAcceptanceRowEntry(
        row_id="BL-X",
        status=GatedRowStatus.STRUCTURED_DEFER,
        structured_defer_fields=StructuredDeferFields(
            owner=nfd_owner,
            impact="i",
            resume_condition="r",
            blocked_by=("B",),
            verification="v",
            target_hash=valid_hash,
        ),
    )
    artifact_nfc = build_gated_acceptance_rows_artifact(
        gated_rows=(row_nfc,),
        required_gated_row_ids=frozenset({"BL-X"}),
        timestamp="2026-05-18T00:00:00+00:00",
    )
    artifact_nfd = build_gated_acceptance_rows_artifact(
        gated_rows=(row_nfd,),
        required_gated_row_ids=frozenset({"BL-X"}),
        timestamp="2026-05-18T00:00:00+00:00",
    )
    # NFC normalize により同じ hash になる (false drift 排除)
    assert artifact_nfc.content_sha256 == artifact_nfd.content_sha256


def test_smoke_metadata_included_in_hash() -> None:
    """Codex F-PR61-002 P2 adopt: smoke stage metadata の改変が smoke_sha256
    に反映される (approval_id / pr_artifact_hash の改ざん detect)。
    """
    from dataclasses import replace
    from types import MappingProxyType

    base = _build_report_all_pass()
    # smoke の最初 stage の metadata を差し替えた report を作る
    new_stages = list(base.smoke_result.stages)
    original_first = new_stages[0]
    tampered_first = SmokeStageResult(
        stage=original_first.stage,
        status=original_first.status,
        duration_ms=original_first.duration_ms,
        metadata=MappingProxyType({"approval_id": "ap-tampered"}),
    )
    new_stages[0] = tampered_first
    tampered_smoke = TicketToPrSmokeResult(
        stage_count=base.smoke_result.stage_count,
        succeeded_count=base.smoke_result.succeeded_count,
        failed_count=base.smoke_result.failed_count,
        skipped_count=base.smoke_result.skipped_count,
        overall_success=base.smoke_result.overall_success,
        stages=tuple(new_stages),
    )
    tampered_report = replace(base, smoke_result=tampered_smoke)

    rows_artifact = build_gated_acceptance_rows_artifact(
        gated_rows=(),
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T03:00:00+00:00",
    )
    chain_clean = build_acceptance_hash_chain(
        report=base,
        gated_rows_artifact=rows_artifact,
        timestamp="2026-05-18T03:00:00+00:00",
    )
    chain_tampered = build_acceptance_hash_chain(
        report=tampered_report,
        gated_rows_artifact=rows_artifact,
        timestamp="2026-05-18T03:00:00+00:00",
    )
    # metadata 改変が smoke_sha256 に反映される
    assert chain_clean.smoke_sha256 != chain_tampered.smoke_sha256
    # 結果 final_chain も変わる (改ざん detect)
    assert chain_clean.final_chain_sha256 != chain_tampered.final_chain_sha256


def test_pass_evidence_persisted_in_artifact() -> None:
    """Codex F-PR61-005 P2 adopt: PASS gated row の pass_evidence が
    artifact rows に永続化される (target_hash / evidence_artifact_hash /
    verified_by / verified_at)。
    """
    from backend.app.services.eval.p0_acceptance_report import PassEvidence

    valid_hash_a = "a" * 64
    valid_hash_b = "b" * 64
    pass_row = GatedAcceptanceRowEntry(
        row_id="BL-Y-pass",
        status=GatedRowStatus.PASS,
        pass_evidence=PassEvidence(
            target_hash=valid_hash_a,
            evidence_artifact_hash=valid_hash_b,
            verified_by="actor:human-verifier",
            verified_at="2026-05-18T04:00:00+00:00",
        ),
    )
    artifact = build_gated_acceptance_rows_artifact(
        gated_rows=(pass_row,),
        required_gated_row_ids=frozenset({"BL-Y-pass"}),
        timestamp="2026-05-18T00:00:00+00:00",
    )
    pe = artifact.rows[0]["pass_evidence"]
    assert pe is not None
    assert pe["target_hash"] == valid_hash_a
    assert pe["evidence_artifact_hash"] == valid_hash_b
    assert pe["verified_by"] == "actor:human-verifier"
    assert pe["verified_at"] == "2026-05-18T04:00:00+00:00"


def test_pass_evidence_missing_raises_value_error() -> None:
    """status=PASS で pass_evidence=None は contract 違反 (Codex F-PR61-005 P2)."""
    with pytest.raises(ValueError, match="pass_evidence is required"):
        GatedAcceptanceRowEntry(
            row_id="BL-Y-pass",
            status=GatedRowStatus.PASS,
            pass_evidence=None,
        )


def test_pass_evidence_invalid_target_hash_raises() -> None:
    """target_hash が SHA-256 hex 形式でなければ ValueError (Codex F-PR61-004 P1)."""
    from backend.app.services.eval.p0_acceptance_report import PassEvidence

    with pytest.raises(ValueError, match="target_hash must be SHA-256 hex"):
        PassEvidence(
            target_hash="todo",  # ← placeholder text、64 hex chars でない
            evidence_artifact_hash="a" * 64,
            verified_by="actor:human",
            verified_at="2026-05-18T04:00:00+00:00",
        )


def test_structured_defer_target_hash_placeholder_rejected() -> None:
    """Codex F-PR61-004 P1 adopt: StructuredDeferFields.target_hash が
    placeholder text "todo" 等で is_schema_valid()=False。
    """
    from backend.app.services.eval.p0_acceptance_report import (
        StructuredDeferFields,
    )

    invalid = StructuredDeferFields(
        owner="actor:human",
        impact="impact",
        resume_condition="cond",
        blocked_by=("BL-X",),
        verification="verify",
        target_hash="todo",  # placeholder
    )
    assert invalid.is_schema_valid() is False
    assert "target_hash_not_sha256_hex" in invalid.missing_fields()


def test_artifact_is_frozen_dataclass() -> None:
    """全 artifact dataclass は frozen (append-only invariant)。"""
    artifact = build_gated_acceptance_rows_artifact(
        gated_rows=(),
        required_gated_row_ids=frozenset(),
        timestamp="2026-05-18T00:00:00+00:00",
    )
    with pytest.raises(AttributeError):
        artifact.content_sha256 = "tampered"  # type: ignore[misc]
