from __future__ import annotations

from typing import Any

from backend.app.services.research.provenance_view import (
    MAX_NODES_PER_KIND,
    PRE_VALIDATION_MAX_NODES_PER_KIND,
    PRE_VALIDATION_MAX_RELATIONS,
    PRE_VALIDATION_MAX_STRING,
    build_provenance_view,
)
from backend.app.services.security.secret_text_scan import REDACTED_PLACEHOLDER


def _valid_bundle() -> dict[str, Any]:
    return {
        "activities": [{"id": "activity:research", "type": "prov:Activity"}],
        "entities": [{"id": "entity:claim", "type": "prov:Entity"}],
        "agents": [{"id": "agent:researcher", "type": "prov:Agent"}],
        "wasGeneratedBy": [{"entity": "entity:claim", "activity": "activity:research"}],
        "wasAttributedTo": [{"entity": "entity:claim", "agent": "agent:researcher"}],
    }


def test_valid_bundle_extracts_structure() -> None:
    view = build_provenance_view(_valid_bundle())
    assert view.valid is True
    assert view.reason is None
    assert [n.id for n in view.activities] == ["activity:research"]
    assert [n.id for n in view.entities] == ["entity:claim"]
    assert [n.id for n in view.agents] == ["agent:researcher"]
    kinds = {r.relation for r in view.relations}
    assert kinds == {"wasGeneratedBy", "wasAttributedTo"}
    gen = next(r for r in view.relations if r.relation == "wasGeneratedBy")
    assert gen.from_id == "entity:claim"
    assert gen.to_id == "activity:research"
    assert view.truncated is False


def test_invalid_bundle_returns_invalid_without_raw() -> None:
    # wasGeneratedBy 必須を満たさない → invalid。raw を露出しない。
    view = build_provenance_view({"activities": [{"id": "a", "type": "prov:Activity"}]})
    assert view.valid is False
    assert view.reason == "invalid_schema"
    assert view.activities == []
    assert view.relations == []


def test_non_dict_provenance_is_invalid() -> None:
    view = build_provenance_view({"entities": "not-a-list"})  # type: ignore[dict-item]
    assert view.valid is False
    assert view.reason == "invalid_schema"


def test_secret_shaped_id_is_redacted() -> None:
    secret_id = "entity:sk-proj-abcdefghijklmnopqrstuvwxyz012345"
    bundle = {
        "activities": [{"id": "activity:research", "type": "prov:Activity"}],
        "entities": [{"id": secret_id, "type": "prov:Entity"}],
        "wasGeneratedBy": [{"entity": secret_id, "activity": "activity:research"}],
    }
    view = build_provenance_view(bundle)
    assert view.valid is True
    assert view.entities[0].id == REDACTED_PLACEHOLDER
    assert view.relations[0].from_id == REDACTED_PLACEHOLDER


def test_oversized_nodes_rejected_before_validation() -> None:
    """Codex adversarial R1 HIGH (F-001): node 極端過多は validation 前に too_large で弾く。"""
    activities = [
        {"id": f"activity:{i}", "type": "prov:Activity"}
        for i in range(PRE_VALIDATION_MAX_NODES_PER_KIND + 1)
    ]
    bundle = {
        "activities": activities,
        "entities": [{"id": "entity:claim", "type": "prov:Entity"}],
        "wasGeneratedBy": [{"entity": "entity:claim", "activity": "activity:0"}],
    }
    view = build_provenance_view(bundle)
    assert view.valid is False
    assert view.reason == "too_large"


def test_oversized_relations_rejected_before_validation() -> None:
    rels = [
        {"entity": "entity:claim", "activity": "activity:research"}
        for _ in range(PRE_VALIDATION_MAX_RELATIONS + 1)
    ]
    bundle = {
        "activities": [{"id": "activity:research", "type": "prov:Activity"}],
        "entities": [{"id": "entity:claim", "type": "prov:Entity"}],
        "wasGeneratedBy": rels,
    }
    view = build_provenance_view(bundle)
    assert view.valid is False
    assert view.reason == "too_large"


def test_oversized_string_rejected_before_validation() -> None:
    bundle = {
        "activities": [{"id": "a:" + "x" * (PRE_VALIDATION_MAX_STRING + 1), "type": "prov:Activity"}],
        "entities": [{"id": "entity:claim", "type": "prov:Entity"}],
        "wasGeneratedBy": [{"entity": "entity:claim", "activity": "activity:research"}],
    }
    view = build_provenance_view(bundle)
    assert view.valid is False
    assert view.reason == "too_large"


def test_prov_namespace_alias_counts_toward_size_limit() -> None:
    """alias key (prov:wasGeneratedBy) も size guard に含める。"""
    rels = [
        {"entity": "entity:claim", "activity": "activity:research"}
        for _ in range(PRE_VALIDATION_MAX_RELATIONS + 1)
    ]
    bundle = {
        "activities": [{"id": "activity:research", "type": "prov:Activity"}],
        "entities": [{"id": "entity:claim", "type": "prov:Entity"}],
        "prov:wasGeneratedBy": rels,
    }
    view = build_provenance_view(bundle)
    assert view.valid is False
    assert view.reason == "too_large"


def test_node_cap_truncates() -> None:
    activities = [{"id": f"activity:{i}", "type": "prov:Activity"} for i in range(MAX_NODES_PER_KIND + 5)]
    bundle = {
        "activities": activities,
        "entities": [{"id": "entity:claim", "type": "prov:Entity"}],
        "wasGeneratedBy": [{"entity": "entity:claim", "activity": "activity:0"}],
    }
    view = build_provenance_view(bundle)
    assert view.valid is True
    assert len(view.activities) == MAX_NODES_PER_KIND
    assert view.truncated is True
