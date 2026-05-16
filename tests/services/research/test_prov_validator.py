from __future__ import annotations

import pytest

from backend.app.services.research.prov_validator import (
    ProvBundle,
    ProvValidationError,
    validate_provenance_json,
)


def _valid_full_bundle() -> dict[str, object]:
    return {
        "activities": [
            {"id": "activity:research", "type": "prov:Activity"},
            {"id": "activity:summarize", "type": "prov:Activity"},
        ],
        "entities": [
            {"id": "entity:source", "type": "prov:Entity"},
            {"id": "entity:claim", "type": "prov:Entity"},
        ],
        "agents": [{"id": "agent:researcher", "type": "prov:Agent"}],
        "wasGeneratedBy": [
            {"entity": "entity:claim", "activity": "activity:summarize"},
        ],
        "used": [
            {"activity": "activity:summarize", "entity": "entity:source"},
        ],
        "wasAttributedTo": [
            {"entity": "entity:claim", "agent": "agent:researcher"},
        ],
        "wasInformedBy": [
            {"informed": "activity:summarize", "informant": "activity:research"},
        ],
        "wasDerivedFrom": [
            {"generated": "entity:claim", "used": "entity:source"},
        ],
    }


def test_validate_provenance_json_accepts_full_five_relation_bundle() -> None:
    bundle = validate_provenance_json(_valid_full_bundle())

    assert isinstance(bundle, ProvBundle)
    assert len(bundle.wasGeneratedBy) == 1
    assert len(bundle.used) == 1
    assert len(bundle.wasAttributedTo) == 1
    assert len(bundle.wasInformedBy) == 1
    assert len(bundle.wasDerivedFrom) == 1


def test_validate_provenance_json_accepts_minimal_bundle() -> None:
    bundle = validate_provenance_json(
        {
            "activities": [{"id": "activity:research", "type": "prov:Activity"}],
            "entities": [{"id": "entity:claim", "type": "prov:Entity"}],
            "wasGeneratedBy": [
                {"entity": "entity:claim", "activity": "activity:research"},
            ],
        }
    )

    assert isinstance(bundle, ProvBundle)
    assert bundle.wasGeneratedBy[0].entity == "entity:claim"


def test_validate_provenance_json_rejects_missing_was_generated_by() -> None:
    payload = _valid_full_bundle()
    payload["wasGeneratedBy"] = []

    with pytest.raises(ProvValidationError, match="wasGeneratedBy"):
        validate_provenance_json(payload)


def test_validate_provenance_json_rejects_unknown_relation_reference() -> None:
    payload = _valid_full_bundle()
    payload["used"] = [{"activity": "activity:missing", "entity": "entity:source"}]

    with pytest.raises(ProvValidationError, match=r"unknown id\(s\)"):
        validate_provenance_json(payload)


def test_validate_provenance_json_rejects_schema_mismatch() -> None:
    payload = _valid_full_bundle()
    payload["activities"] = [{"id": "activity:research", "type": 1}]

    with pytest.raises(ProvValidationError):
        validate_provenance_json(payload)


def test_validate_provenance_json_rejects_empty_dict() -> None:
    with pytest.raises(ProvValidationError, match="wasGeneratedBy"):
        validate_provenance_json({})
