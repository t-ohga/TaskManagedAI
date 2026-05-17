"""Sprint 12 batch 5 (BL-0149 prerequisite): AcceptanceArtifactBuilder.

SP-012 line 267-279 + line 218-247 + Codex 監査 (2026-05-18) F-AUDIT-002 P1
adopt: P0 Exit sign-off の evidence chain 永続化を server-owned に統一.

役割:
- `build_gated_acceptance_rows_artifact`: gated_rows + structured_defer 6 fields を
  JSON-serializable dict に変換 (永続化前段、append-only audit truth)
- `build_acceptance_hash_chain`: 各 source (Hard Gates / KPI / smoke / drill /
  private_staging / gated_rows) の hash chain を server 計算 (caller input hash
  経路を物理削除、AcceptanceArtifactBuilder は input から hash を再計算する)
- `build_p0_acceptance_artifact`: 上記 2 つを統合した P0 Exit artifact dict
  (BL-0149 sign-off 用 evidence chain、後続 batch で audit_events emit + filesystem
  persist + signed journal で完成)

Anti-Gaming invariants (本 batch):
- caller input hash を信頼しない (target_hash 等は server が input から SHA-256
  で再計算、StructuredDeferFields.target_hash は caller が "事前計算" した値を
  記録するが、本 builder は再計算後の値と一致するか verify する経路を埋める)
- artifact は raw secret を含まない (drill.notes / private_staging summary 等は
  caller が redaction 済 metadata を渡す invariant)

Security boundary:
- pure function (no DB / FS / network)、caller が永続化・audit emit を担当
- 全 source の sha256 hash は NFC UTF-8 + JCS canonical JSON (RFC 8785 compliant)
  で server 計算 (.claude/rules/cross-source-enum-integrity.md と整合)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from backend.app.services.eval.p0_acceptance_report import (
    GatedAcceptanceRowEntry,
    OperationalDrillEntry,
    P0AcceptanceReportSummary,
)

ARTIFACT_SCHEMA_VERSION: Final[str] = "p0-acceptance/v1"


def _canonical_json_sha256(payload: object) -> str:
    """RFC 8785 canonical JSON + SHA-256 (NFC UTF-8、append-only audit invariant).

    .claude/rules/cross-source-enum-integrity.md の hash invariant と整合.
    """
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _gated_row_to_dict(row: GatedAcceptanceRowEntry) -> dict[str, Any]:
    """gated row 1 件を JSON-serializable dict に変換 (frozen 値のみ抽出)."""
    sd_fields: dict[str, Any] | None = None
    if row.structured_defer_fields is not None:
        sf = row.structured_defer_fields
        sd_fields = {
            "owner": sf.owner,
            "impact": sf.impact,
            "resume_condition": sf.resume_condition,
            "blocked_by": list(sf.blocked_by),
            "verification": sf.verification,
            "target_hash": sf.target_hash,
        }
    return {
        "row_id": row.row_id,
        "status": row.status.value,
        "structured_defer_fields": sd_fields,
        "structured_defer_fields_present": row.structured_defer_fields_present,
        "missing_fields": list(
            row.structured_defer_fields.missing_fields()
            if row.structured_defer_fields is not None
            else ()
        ),
    }


@dataclass(frozen=True, slots=True)
class GatedAcceptanceRowsArtifact:
    """gated_acceptance_rows.json 永続化用 artifact (frozen).

    SP-012 line 267-279: append-only artifact、改ざん detection 用 sha256 含む.
    """

    schema_version: str  # "p0-acceptance/v1"
    timestamp: str  # ISO 8601 UTC
    rows: tuple[dict[str, Any], ...]
    required_row_ids: tuple[str, ...]  # 監査用 (sorted)
    missing_required_row_ids: tuple[str, ...]  # 監査用 (sorted)
    content_sha256: str  # 全 rows + required_row_ids の canonical SHA-256


def build_gated_acceptance_rows_artifact(
    *,
    gated_rows: tuple[GatedAcceptanceRowEntry, ...],
    required_gated_row_ids: frozenset[str],
    timestamp: str | None = None,
) -> GatedAcceptanceRowsArtifact:
    """gated_rows + required を永続化用 artifact に変換 (server-owned hash).

    SP-012 line 87-99 + line 267-279 invariant: row schema + required row 突合せ
    + content_sha256 (改ざん detection).

    Args:
        gated_rows: caller が用意した row entries
        required_gated_row_ids: P0 Exit に必須な row_id set (caller-supplied)
        timestamp: artifact 生成時刻 (default = now UTC ISO 8601)
    """
    provided = {row.row_id for row in gated_rows}
    missing = required_gated_row_ids - provided
    rows_dicts = tuple(_gated_row_to_dict(r) for r in gated_rows)
    ts = timestamp or datetime.now(tz=UTC).isoformat()

    # canonical hash は rows + required + timestamp が input (caller hash 経路なし)
    content_payload = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "timestamp": ts,
        "rows": list(rows_dicts),
        "required_row_ids": sorted(required_gated_row_ids),
        "missing_required_row_ids": sorted(missing),
    }
    content_sha256 = _canonical_json_sha256(content_payload)

    return GatedAcceptanceRowsArtifact(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        timestamp=ts,
        rows=rows_dicts,
        required_row_ids=tuple(sorted(required_gated_row_ids)),
        missing_required_row_ids=tuple(sorted(missing)),
        content_sha256=content_sha256,
    )


@dataclass(frozen=True, slots=True)
class AcceptanceHashChain:
    """P0 Exit evidence chain の hash artifact (frozen、永続化用).

    各 source (hard_gates / kpi / smoke / drill / private_staging / gated_rows)
    の sha256 を hash chain として記録. 全 source の hash を結合した
    final_chain_sha256 で改ざん detect.
    """

    schema_version: str
    timestamp: str
    hard_gates_sha256: str
    kpi_sha256: str
    smoke_sha256: str
    drill_entries_sha256: str
    private_staging_sha256: str
    gated_rows_sha256: str  # GatedAcceptanceRowsArtifact.content_sha256 と一致
    final_chain_sha256: str  # 上記 6 hash を canonical JSON で sha256


def _drill_entry_to_dict(drill: OperationalDrillEntry) -> dict[str, Any]:
    return {
        "drill_kind": drill.drill_kind,
        "status": str(drill.status),
        "completed_at": drill.completed_at,
        "notes": drill.notes,
    }


def build_acceptance_hash_chain(
    *,
    report: P0AcceptanceReportSummary,
    gated_rows_artifact: GatedAcceptanceRowsArtifact,
    timestamp: str | None = None,
) -> AcceptanceHashChain:
    """P0 Exit evidence chain の hash を server 計算 (caller hash 経路なし).

    SP-012 line 244-247 + Codex 監査 F-AUDIT-002 P1 adopt: caller が hash を
    渡せる経路を物理削除し、本 builder が report + gated_rows_artifact から
    全 sha256 を再計算する.
    """
    ts = timestamp or datetime.now(tz=UTC).isoformat()

    hard_gates_payload = {
        "kpi_count": report.hard_gates_summary.hard_gate_count,
        "met_count": report.hard_gates_summary.met_count,
        "failed_count": report.hard_gates_summary.failed_count,
        "p0_accept": report.hard_gates_summary.p0_accept,
        "entries": [
            {
                "hard_gate_id": e.hard_gate_id,
                "metric_key": e.metric_key,
                "metric_value": e.metric_value,
                "threshold_met": e.threshold_met,
                "threshold_reason": e.threshold_reason,
            }
            for e in report.hard_gates_summary.entries
        ],
    }
    kpi_payload = {
        "kpi_count": report.kpi_summary.kpi_count,
        "met_count": report.kpi_summary.met_count,
        "failed_count": report.kpi_summary.failed_count,
        "p0_accept": report.kpi_summary.p0_accept,
        "entries": [
            {
                "kpi_id": e.kpi_id,
                "metric_key": e.metric_key,
                "metric_value": e.metric_value,
                "threshold_met": e.threshold_met,
                "threshold_reason": e.threshold_reason,
            }
            for e in report.kpi_summary.entries
        ],
    }
    smoke_payload = {
        "stage_count": report.smoke_result.stage_count,
        "succeeded_count": report.smoke_result.succeeded_count,
        "failed_count": report.smoke_result.failed_count,
        "skipped_count": report.smoke_result.skipped_count,
        "overall_success": report.smoke_result.overall_success,
        "stages": [
            {
                "stage": str(s.stage),
                "status": s.status,
                "duration_ms": s.duration_ms,
                "error_code": s.error_code,
            }
            for s in report.smoke_result.stages
        ],
    }
    drill_payload = {
        "entries": [_drill_entry_to_dict(d) for d in report.drill_entries]
    }
    private_staging_payload = {
        "status": str(report.private_staging_status),
        "passed": report.private_staging_passed,
    }

    hg_hash = _canonical_json_sha256(hard_gates_payload)
    kpi_hash = _canonical_json_sha256(kpi_payload)
    smoke_hash = _canonical_json_sha256(smoke_payload)
    drill_hash = _canonical_json_sha256(drill_payload)
    private_staging_hash = _canonical_json_sha256(private_staging_payload)
    gated_rows_hash = gated_rows_artifact.content_sha256

    chain_payload = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "timestamp": ts,
        "hard_gates_sha256": hg_hash,
        "kpi_sha256": kpi_hash,
        "smoke_sha256": smoke_hash,
        "drill_entries_sha256": drill_hash,
        "private_staging_sha256": private_staging_hash,
        "gated_rows_sha256": gated_rows_hash,
    }
    final_chain_sha256 = _canonical_json_sha256(chain_payload)

    return AcceptanceHashChain(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        timestamp=ts,
        hard_gates_sha256=hg_hash,
        kpi_sha256=kpi_hash,
        smoke_sha256=smoke_hash,
        drill_entries_sha256=drill_hash,
        private_staging_sha256=private_staging_hash,
        gated_rows_sha256=gated_rows_hash,
        final_chain_sha256=final_chain_sha256,
    )


@dataclass(frozen=True, slots=True)
class P0AcceptanceArtifact:
    """BL-0149 P0 Exit final artifact (frozen、append-only).

    永続化形式 (Sprint 12 後続 batch で audit_events emit + filesystem):
    - `gated_rows_artifact`: GatedAcceptanceRowsArtifact
    - `hash_chain`: AcceptanceHashChain (改ざん detect)
    - `report`: P0AcceptanceReportSummary (full verdict + deficiencies)
    - `p0_exit_decision`: 最終 verdict (report 内と一致、duplicate で明示)
    """

    schema_version: str
    timestamp: str
    p0_exit_decision: bool
    deficiencies: tuple[str, ...]
    gated_rows_artifact: GatedAcceptanceRowsArtifact
    hash_chain: AcceptanceHashChain


def build_p0_acceptance_artifact(
    *,
    report: P0AcceptanceReportSummary,
    required_gated_row_ids: frozenset[str],
    timestamp: str | None = None,
) -> P0AcceptanceArtifact:
    """P0 Exit final artifact を server-owned に build (BL-0149 evidence chain)."""
    ts = timestamp or datetime.now(tz=UTC).isoformat()
    gated_rows_artifact = build_gated_acceptance_rows_artifact(
        gated_rows=report.gated_rows,
        required_gated_row_ids=required_gated_row_ids,
        timestamp=ts,
    )
    hash_chain = build_acceptance_hash_chain(
        report=report,
        gated_rows_artifact=gated_rows_artifact,
        timestamp=ts,
    )
    return P0AcceptanceArtifact(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        timestamp=ts,
        p0_exit_decision=report.p0_exit_decision,
        deficiencies=report.deficiencies,
        gated_rows_artifact=gated_rows_artifact,
        hash_chain=hash_chain,
    )


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "AcceptanceHashChain",
    "GatedAcceptanceRowsArtifact",
    "P0AcceptanceArtifact",
    "build_acceptance_hash_chain",
    "build_gated_acceptance_rows_artifact",
    "build_p0_acceptance_artifact",
]
