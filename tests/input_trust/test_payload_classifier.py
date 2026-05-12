"""payload_data_class classifier tests (Sprint 5.5 BL-0066).

Verifies that ``payload_data_class`` is computed server-side from artifact /
request metadata only — caller-supplied paths are rejected at the
``PayloadClassificationInput`` schema layer (``extra="forbid"``,
`.claude/rules/server-owned-boundary.md` §1).
"""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import ValidationError

from backend.app.services.input_trust.payload_classifier import (
    PayloadClassificationInput,
    PayloadClassificationResult,
    classify_payload_data_class,
)


def test_caller_supplied_payload_data_class_is_rejected_at_schema() -> None:
    with pytest.raises(ValidationError) as exc:
        PayloadClassificationInput.model_validate(
            {
                "content_sensitivity_hints": [],
                "payload_data_class": "pii",  # hostile caller injection
            }
        )
    assert "payload_data_class" in str(exc.value)


def test_unknown_extra_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PayloadClassificationInput.model_validate(
            {
                "content_sensitivity_hints": [],
                "effective_allowed_data_class": "pii",
            }
        )


def test_empty_input_internal_origin_defaults_public() -> None:
    payload = PayloadClassificationInput()
    result = classify_payload_data_class(payload)
    assert isinstance(result, PayloadClassificationResult)
    assert result.payload_data_class == "public"
    assert result.reason_codes == ("internal_origin_default_public",)


def test_empty_input_external_origin_defaults_internal() -> None:
    payload = PayloadClassificationInput(external_origin=True)
    result = classify_payload_data_class(payload)
    assert result.payload_data_class == "internal"
    assert result.reason_codes == ("external_origin_default_internal",)


def test_pii_marker_promotes_to_pii() -> None:
    payload = PayloadClassificationInput(contains_pii_markers=True)
    result = classify_payload_data_class(payload)
    assert result.payload_data_class == "pii"
    assert "explicit_pii_hint" in result.reason_codes


def test_confidential_marker_promotes_to_confidential() -> None:
    payload = PayloadClassificationInput(contains_confidential_markers=True)
    result = classify_payload_data_class(payload)
    assert result.payload_data_class == "confidential"
    assert "explicit_confidential_hint" in result.reason_codes


def test_pii_dominates_confidential_when_both_markers_present() -> None:
    payload = PayloadClassificationInput(
        contains_pii_markers=True,
        contains_confidential_markers=True,
    )
    result = classify_payload_data_class(payload)
    assert result.payload_data_class == "pii"
    assert set(result.reason_codes) == {
        "explicit_pii_hint",
        "explicit_confidential_hint",
    }


def test_hints_list_promotes_to_highest_value() -> None:
    payload = PayloadClassificationInput(
        content_sensitivity_hints=["internal", "confidential", "pii"],
    )
    result = classify_payload_data_class(payload)
    assert result.payload_data_class == "pii"


def test_internal_hint_promotes_only_to_internal() -> None:
    payload = PayloadClassificationInput(
        content_sensitivity_hints=["internal"],
    )
    result = classify_payload_data_class(payload)
    assert result.payload_data_class == "internal"
    assert result.reason_codes == ("explicit_internal_hint",)


def test_public_hint_alone_yields_public_default_path() -> None:
    """`public` hint contributes no upper bound; default path applies."""

    payload = PayloadClassificationInput(
        content_sensitivity_hints=["public"],
        external_origin=False,
    )
    result = classify_payload_data_class(payload)
    assert result.payload_data_class == "public"


def test_external_origin_with_public_hint_still_external_default() -> None:
    payload = PayloadClassificationInput(
        content_sensitivity_hints=["public"],
        external_origin=True,
    )
    result = classify_payload_data_class(payload)
    assert result.payload_data_class == "internal"
    assert result.reason_codes == ("external_origin_default_internal",)


def test_reason_codes_are_immutable_tuple() -> None:
    payload = PayloadClassificationInput(contains_pii_markers=True)
    result = classify_payload_data_class(payload)
    assert isinstance(result.reason_codes, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.payload_data_class = "public"  # type: ignore[misc]
