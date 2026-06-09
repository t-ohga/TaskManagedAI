"""SP-027 (ADR-00053): provenance 構造化 view builder (read-only、raw 非展開)。

``validate_provenance_json`` (prov_validator) で W3C PROV-DM minimal subset を validate し、id/type を
``redact_if_secret`` (SP-032 broad scanner) で redact、size cap を適用した構造のみ返す。invalid な
provenance_json は ``{valid: false, reason: "invalid_schema"}`` を返し raw を露出しない (SP-010 invariant)。
"""

from __future__ import annotations

from typing import Any

from backend.app.schemas.provenance_view import (
    ProvenanceView,
    ProvNodeView,
    ProvRelationView,
)
from backend.app.services.research.prov_validator import (
    ProvValidationError,
    validate_provenance_json,
)
from backend.app.services.security.secret_text_scan import redact_if_secret

# R1 F-012: display cap (validation 後の view truncation、moderate oversize は表示を切り詰める)。
MAX_NODES_PER_KIND = 200
MAX_RELATIONS = 500
MAX_STRING_LENGTH = 128
# Codex adversarial R1 HIGH (F-001): validation **前**に弾く DoS cap (validate_provenance_json は bundle を
# materialize し ids/refs を walk するため、巨大 valid bundle が read CPU を焼く)。display cap より高い
# 上限で、moderate oversize は validate + 表示 truncation、extreme oversize は too_large で reject する。
PRE_VALIDATION_MAX_NODES_PER_KIND = 2000
PRE_VALIDATION_MAX_RELATIONS = 5000
PRE_VALIDATION_MAX_STRING = 1024

_NODE_KEYS = (
    "activities", "prov:activities", "entities", "prov:entities", "agents", "prov:agents",
)
_RELATION_KEYS = (
    "wasGeneratedBy", "prov:wasGeneratedBy", "used", "prov:used",
    "wasAttributedTo", "prov:wasAttributedTo", "wasInformedBy", "prov:wasInformedBy",
    "wasDerivedFrom", "prov:wasDerivedFrom",
)


def _within_size_limits(provenance_json: dict[str, Any]) -> bool:
    """validation 前の cheap size guard (DoS、R1 F-001)。

    node list / relation 総数を O(1) の len() で bound し、count が範囲内なら bounded な要素を
    走査して string field 長も bound する (count cap 通過後の iteration は有界)。
    """
    # node list は各 kind ≤ PRE_VALIDATION_MAX_NODES_PER_KIND (O(1) len check)。
    for key in _NODE_KEYS:
        value = provenance_json.get(key)
        if isinstance(value, list) and len(value) > PRE_VALIDATION_MAX_NODES_PER_KIND:
            return False
    # relation 総数 ≤ PRE_VALIDATION_MAX_RELATIONS。
    relation_total = 0
    for key in _RELATION_KEYS:
        value = provenance_json.get(key)
        if isinstance(value, list):
            relation_total += len(value)
    if relation_total > PRE_VALIDATION_MAX_RELATIONS:
        return False
    # count が bound 済 → bounded な要素を走査し string 長を bound (1 要素巨大 string の DoS)。
    for key in (*_NODE_KEYS, *_RELATION_KEYS):
        value = provenance_json.get(key)
        if not isinstance(value, list):
            continue
        for element in value:
            if isinstance(element, dict):
                for field_value in element.values():
                    if isinstance(field_value, str) and len(field_value) > PRE_VALIDATION_MAX_STRING:
                        return False
    return True


def _safe_str(value: str) -> str:
    """secret-shaped を redact し、過長を切り詰める (read 露出の defense-in-depth)。"""
    redacted = redact_if_secret(value)
    text = redacted if redacted is not None else value
    if len(text) > MAX_STRING_LENGTH:
        return text[:MAX_STRING_LENGTH]
    return text


def build_provenance_view(provenance_json: dict[str, Any]) -> ProvenanceView:
    """claim.provenance_json から構造化 PROV view を組み立てる。

    oversized は validation 前に弾く (`too_large`、DoS)。invalid なら ``{valid: false,
    reason: "invalid_schema"}`` (raw 非露出)。valid なら nodes / relations を redact + cap して返す。
    """
    # R1 F-001: validation 前に size を bound (expensive validation を short-circuit)。
    if not _within_size_limits(provenance_json):
        return ProvenanceView(valid=False, reason="too_large")
    try:
        bundle = validate_provenance_json(provenance_json)
    except ProvValidationError:
        # raw path / raw id / validator detail は返さない (固定 reason enum のみ)。
        return ProvenanceView(valid=False, reason="invalid_schema")

    truncated = False

    def _nodes(items: list[Any]) -> list[ProvNodeView]:
        nonlocal truncated
        if len(items) > MAX_NODES_PER_KIND:
            truncated = True
            items = items[:MAX_NODES_PER_KIND]
        return [ProvNodeView(id=_safe_str(node.id), type=_safe_str(node.type)) for node in items]

    activities = _nodes(list(bundle.activities))
    entities = _nodes(list(bundle.entities))
    agents = _nodes(list(bundle.agents))

    relations: list[ProvRelationView] = []
    # (relation kind, from-attr, to-attr) の canonical mapping。
    relation_specs: list[tuple[str, list[Any], str, str]] = [
        ("wasGeneratedBy", list(bundle.wasGeneratedBy), "entity", "activity"),
        ("used", list(bundle.used), "activity", "entity"),
        ("wasAttributedTo", list(bundle.wasAttributedTo), "entity", "agent"),
        ("wasInformedBy", list(bundle.wasInformedBy), "informed", "informant"),
        ("wasDerivedFrom", list(bundle.wasDerivedFrom), "generated", "used"),
    ]
    for kind, rels, from_attr, to_attr in relation_specs:
        for rel in rels:
            if len(relations) >= MAX_RELATIONS:
                truncated = True
                break
            relations.append(
                ProvRelationView(
                    relation=kind,
                    from_id=_safe_str(getattr(rel, from_attr)),
                    to_id=_safe_str(getattr(rel, to_attr)),
                )
            )

    return ProvenanceView(
        valid=True,
        reason=None,
        activities=activities,
        entities=entities,
        agents=agents,
        relations=relations,
        truncated=truncated,
    )


__all__ = [
    "MAX_NODES_PER_KIND",
    "MAX_RELATIONS",
    "MAX_STRING_LENGTH",
    "build_provenance_view",
]
