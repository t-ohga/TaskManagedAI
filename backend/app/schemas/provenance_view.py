"""SP-027 (ADR-00053): provenance 構造化 view の read schema。

raw provenance_json は展開しない (SP-010 invariant)。``prov_validator.ProvBundle`` で validate 済の
構造を抽出し、全 string (id / type) を redact、size cap を適用したものだけ返す。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ProvRelationKind = Literal[
    "wasGeneratedBy", "used", "wasAttributedTo", "wasInformedBy", "wasDerivedFrom"
]
# R1 F-001 (adversarial): oversized は validation 前に弾く (DoS)、reason で区別。
ProvenanceInvalidReason = Literal["invalid_schema", "too_large"]


class ProvNodeView(BaseModel):
    id: str
    type: str


class ProvRelationView(BaseModel):
    relation: ProvRelationKind
    from_id: str
    to_id: str


class ProvenanceView(BaseModel):
    valid: bool
    reason: ProvenanceInvalidReason | None = None
    activities: list[ProvNodeView] = []
    entities: list[ProvNodeView] = []
    agents: list[ProvNodeView] = []
    relations: list[ProvRelationView] = []
    # R1 F-012: nodes/relations/str の cap 超過時に true。
    truncated: bool = False


__all__ = [
    "ProvNodeView",
    "ProvRelationKind",
    "ProvRelationView",
    "ProvenanceInvalidReason",
    "ProvenanceView",
]
