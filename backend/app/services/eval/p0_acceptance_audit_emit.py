"""Sprint 12 batch 6 (BL-0149 evidence chain): P0 acceptance audit event emit.

`audit_events.p0_acceptance_report_generated` event payload を server-owned
で構築する service function. 実 DB write は別 batch (本 batch では payload
schema + redaction + audit_event_type contract のみ確定).

audit invariant (.claude/rules/secretbroker-boundary.md §11):
- raw secret / capability token 生値は payload に含まない
- hash chain final_sha256 は append-only audit chain で改ざん detect
- actor_id / tenant_id / event_payload は caller (BL-0149 sign-off step) が
  渡す責務
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from backend.app.services.eval.acceptance_artifact_builder import (
    P0AcceptanceArtifact,
)

# audit_events.event_type 固定文字列 (cross-source-enum-integrity §1 と整合).
# rules/agentrun-state-machine.md §6 + DD-04 audit event registry に追加.
AUDIT_EVENT_TYPE_P0_ACCEPTANCE_REPORT_GENERATED: Final[str] = (
    "p0_acceptance_report_generated"
)


@dataclass(frozen=True, slots=True)
class P0AcceptanceAuditPayload:
    """audit_events.event_payload schema (frozen、append-only audit truth).

    JSON-serializable な dict にして実 DB write は caller が担当.
    `final_chain_sha256` のみ artifact hash chain と一致 (caller が verify 可能).
    """

    schema_version: str  # ARTIFACT_SCHEMA_VERSION と同
    timestamp: str  # ISO 8601 UTC
    p0_exit_decision: bool
    deficiency_count: int
    deficiency_codes: tuple[str, ...]  # deficiency 文字列の先頭 code (raw secret なし)
    final_chain_sha256: str  # AcceptanceHashChain.final_chain_sha256
    gated_rows_sha256: str
    hard_gates_sha256: str
    kpi_sha256: str
    smoke_sha256: str
    drill_entries_sha256: str
    private_staging_sha256: str

    def to_dict(self) -> dict[str, Any]:
        """audit_events.event_payload 用 JSON-serializable dict."""
        return {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "p0_exit_decision": self.p0_exit_decision,
            "deficiency_count": self.deficiency_count,
            "deficiency_codes": list(self.deficiency_codes),
            "final_chain_sha256": self.final_chain_sha256,
            "gated_rows_sha256": self.gated_rows_sha256,
            "hard_gates_sha256": self.hard_gates_sha256,
            "kpi_sha256": self.kpi_sha256,
            "smoke_sha256": self.smoke_sha256,
            "drill_entries_sha256": self.drill_entries_sha256,
            "private_staging_sha256": self.private_staging_sha256,
        }


def _extract_deficiency_codes(deficiencies: tuple[str, ...]) -> tuple[str, ...]:
    """deficiency 文字列から先頭 code (raw value なし) を抽出.

    例: "hard_gates_failed (failed_count=2/7, fail_tolerance=0)" → "hard_gates_failed"
    audit payload には raw 値 (count 等) を含まず、code symbol のみ.
    """
    codes: list[str] = []
    for d in deficiencies:
        # 最初の空白までを code として扱う (` (` で続く詳細部分を捨てる)
        code = d.split(" ")[0].split("(")[0].strip()
        if code:
            codes.append(code)
    return tuple(codes)


def build_p0_acceptance_audit_payload(
    *,
    artifact: P0AcceptanceArtifact,
) -> P0AcceptanceAuditPayload:
    """P0AcceptanceArtifact から audit payload を server-owned で構築.

    raw secret invariant: artifact 自体は raw secret を含まないが、audit emit
    側でも double check として deficiency_codes のみ抽出 (raw value 排除).
    """
    return P0AcceptanceAuditPayload(
        schema_version=artifact.schema_version,
        timestamp=artifact.timestamp,
        p0_exit_decision=artifact.p0_exit_decision,
        deficiency_count=len(artifact.deficiencies),
        deficiency_codes=_extract_deficiency_codes(artifact.deficiencies),
        final_chain_sha256=artifact.hash_chain.final_chain_sha256,
        gated_rows_sha256=artifact.hash_chain.gated_rows_sha256,
        hard_gates_sha256=artifact.hash_chain.hard_gates_sha256,
        kpi_sha256=artifact.hash_chain.kpi_sha256,
        smoke_sha256=artifact.hash_chain.smoke_sha256,
        drill_entries_sha256=artifact.hash_chain.drill_entries_sha256,
        private_staging_sha256=artifact.hash_chain.private_staging_sha256,
    )


__all__ = [
    "AUDIT_EVENT_TYPE_P0_ACCEPTANCE_REPORT_GENERATED",
    "P0AcceptanceAuditPayload",
    "build_p0_acceptance_audit_payload",
]
