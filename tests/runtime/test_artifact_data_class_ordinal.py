from __future__ import annotations

from typing import get_args

from backend.app.domain.artifact.data_class import (
    ALL_PAYLOAD_DATA_CLASSES,
    DATA_CLASS_ORDINAL,
    PayloadDataClass,
)


def test_data_class_ordinal_matches_contract() -> None:
    assert DATA_CLASS_ORDINAL == {
        "public": 0,
        "internal": 1,
        "confidential": 2,
        "pii": 3,
    }


def test_data_class_ordinal_supports_ordered_comparison() -> None:
    assert DATA_CLASS_ORDINAL["public"] < DATA_CLASS_ORDINAL["internal"]
    assert DATA_CLASS_ORDINAL["internal"] < DATA_CLASS_ORDINAL["confidential"]
    assert DATA_CLASS_ORDINAL["confidential"] < DATA_CLASS_ORDINAL["pii"]


def test_all_payload_data_classes_match_literal_values() -> None:
    assert tuple(get_args(PayloadDataClass)) == ALL_PAYLOAD_DATA_CLASSES
    assert set(ALL_PAYLOAD_DATA_CLASSES) == set(DATA_CLASS_ORDINAL)
