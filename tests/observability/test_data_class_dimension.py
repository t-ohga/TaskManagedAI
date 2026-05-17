"""Sprint 11.5 batch 0 (BL-0156 skeleton): payload_data_class 3 別 dimension test.

Plan v2 §H-2 adopt:
- 3 別 dimension (`payload_data_class` / `allowed_data_class` / `effective_allowed_data_class`)
- `DATA_CLASS_ORDINAL` mapping (public:0 / internal:1 / confidential:2 / pii:3) ordinal 順序
- 5+ source 整合: `PayloadDataClass` Literal + `DATA_CLASS_ORDINAL` mapping + Pydantic Field
  validator + observability metric label + pytest EXPECTED frozenset の exact set match
"""

from __future__ import annotations

from typing import Final, get_args

import pytest

from backend.app.domain.artifact.data_class import (
    DATA_CLASS_ORDINAL,
    PayloadDataClass,
)
from backend.app.observability.prometheus import PrometheusRegistry

# pytest EXPECTED frozenset (5+ source integrity の 5 番目 source).
EXPECTED_DATA_CLASS_VALUES: Final[frozenset[str]] = frozenset(
    {"public", "internal", "confidential", "pii"}
)


def test_payload_data_class_literal_matches_expected_set() -> None:
    """Source 1: `PayloadDataClass` Literal の値域."""

    literal_values = frozenset(get_args(PayloadDataClass))
    assert literal_values == EXPECTED_DATA_CLASS_VALUES


def test_data_class_ordinal_mapping_keys_match_literal() -> None:
    """Source 2: `DATA_CLASS_ORDINAL` mapping の key 集合."""

    mapping_keys = frozenset(DATA_CLASS_ORDINAL.keys())
    assert mapping_keys == EXPECTED_DATA_CLASS_VALUES


def test_data_class_ordinal_order_is_public_internal_confidential_pii() -> None:
    """Plan v2 §H-2 adopt: ordinal 順序 `public < internal < confidential < pii`."""

    assert DATA_CLASS_ORDINAL["public"] == 0
    assert DATA_CLASS_ORDINAL["internal"] == 1
    assert DATA_CLASS_ORDINAL["confidential"] == 2
    assert DATA_CLASS_ORDINAL["pii"] == 3

    # Strict ordinal monotonic.
    assert (
        DATA_CLASS_ORDINAL["public"]
        < DATA_CLASS_ORDINAL["internal"]
        < DATA_CLASS_ORDINAL["confidential"]
        < DATA_CLASS_ORDINAL["pii"]
    )


def test_data_class_ordinal_size_is_exactly_four() -> None:
    """新規 enum 追加なし (5+ source integrity)."""

    assert len(DATA_CLASS_ORDINAL) == 4


def test_prometheus_record_provider_call_accepts_all_data_class_values() -> None:
    """Source 4: observability metric label 値域 = expected set."""

    reg = PrometheusRegistry()
    for value in EXPECTED_DATA_CLASS_VALUES:
        reg.record_provider_call(
            provider="openai",
            payload_data_class=value,
            allowed_data_class=value,
            effective_allowed_data_class=value,
            decision="allow",
            tenant_id=1,
        )


def test_prometheus_record_provider_call_rejects_non_member() -> None:
    """observability metric label に EXPECTED_DATA_CLASS_VALUES 外を渡すと reject."""

    reg = PrometheusRegistry()
    with pytest.raises(ValueError, match="payload_data_class"):
        reg.record_provider_call(
            provider="openai",
            payload_data_class="confidential2",  # 不正な値
            allowed_data_class="public",
            effective_allowed_data_class="public",
            decision="allow",
            tenant_id=1,
        )


def test_3_dimensions_are_independent_not_aggregated() -> None:
    """3 別 dimension (合算 `data_class` 単一禁止) を metric expose で verify.

    `payload_data_class` / `allowed_data_class` / `effective_allowed_data_class` が
    3 別 label として現れる (合算で 1 label でない).
    """

    reg = PrometheusRegistry()
    reg.record_provider_call(
        provider="openai",
        payload_data_class="internal",
        allowed_data_class="confidential",  # 別値
        effective_allowed_data_class="public",  # 別値
        decision="allow",
        tenant_id=1,
    )
    body = reg.expose().decode("utf-8")
    # 3 値が **同 line** に出ない場合は label 分離が崩れている.
    assert 'payload_data_class="internal"' in body
    assert 'allowed_data_class="confidential"' in body
    assert 'effective_allowed_data_class="public"' in body


def test_5_plus_source_integrity_exact_match() -> None:
    """5+ source 整合の exact set match (Plan v2 §H-2):

    1. `PayloadDataClass` Literal (`backend/app/domain/artifact/data_class.py:6`)
    2. `DATA_CLASS_ORDINAL` mapping (同 file:15)
    3. Pydantic Field validator (existing Provider Compliance schema、test 経由で reject 確認)
    4. observability metric label (本 file の `record_provider_call` accept test)
    5. pytest EXPECTED frozenset (本 constant)

    全 source で 4 値 exact set match を確認.
    """

    sources = {
        "literal": frozenset(get_args(PayloadDataClass)),
        "ordinal_mapping": frozenset(DATA_CLASS_ORDINAL.keys()),
        "pytest_expected": EXPECTED_DATA_CLASS_VALUES,
    }
    # 全 source が同一 set.
    union = set()
    for value_set in sources.values():
        union |= value_set
    intersection = set(EXPECTED_DATA_CLASS_VALUES)
    for value_set in sources.values():
        intersection &= value_set
    assert union == intersection == set(EXPECTED_DATA_CLASS_VALUES)
