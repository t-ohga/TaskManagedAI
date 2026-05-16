from __future__ import annotations

from backend.app.services.research.prov_validator import (
    ProvBundle,
    validate_provenance_json,
)


def test_prov_was_generated_by_namespace_sample_is_valid() -> None:
    bundle = validate_provenance_json(
        {
            "activities": [{"id": "activity:research", "type": "prov:Activity"}],
            "entities": [{"id": "entity:claim", "type": "prov:Entity"}],
            "prov:wasGeneratedBy": [
                {"entity": "entity:claim", "activity": "activity:research"},
            ],
        }
    )

    assert bundle.wasGeneratedBy[0].entity == "entity:claim"


def test_prov_bundle_declares_all_five_relation_fields() -> None:
    fields = set(ProvBundle.model_fields)

    assert {
        "wasGeneratedBy",
        "used",
        "wasAttributedTo",
        "wasInformedBy",
        "wasDerivedFrom",
    } <= fields


def test_prov_relation_field_names_are_w3c_camel_case() -> None:
    relation_fields = [
        field_name
        for field_name in ProvBundle.model_fields
        if field_name.startswith("was") or field_name == "used"
    ]

    assert relation_fields == [
        "wasGeneratedBy",
        "used",
        "wasAttributedTo",
        "wasInformedBy",
        "wasDerivedFrom",
    ]
