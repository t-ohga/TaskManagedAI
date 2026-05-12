"""Sprint 5.5 BL-0068: repair retry context redaction tests.

Asserts fail-closed semantics of ``build_retry_prompt_input``: any raw
secret / provider key / capability token / canary pattern in the previous
artifact or validation error MUST raise ``ValueError`` before the retry
prompt is constructed. This is the regression guard for the
``secret_canary_no_leak`` (AC-HARD-02) invariant on the repair-retry path.

SP55-B3-F-002 fix: the prohibited-key reject parametrize uses the canonical
``_PROHIBITED_PAYLOAD_KEYS`` from the shared scanner so every drift in the
canonical set is caught locally too (in addition to the shared scanner's
own parity tests).

SP55-B3-F-001 fix: nested mutation regression test verifies that the stored
``RetryPromptInput`` dicts are deep copies and cannot be polluted by
post-construction mutation of the caller's input graph.
"""

from __future__ import annotations

import dataclasses

import pytest

from backend.app.repositories._payload_secret_scan import _PROHIBITED_PAYLOAD_KEYS
from backend.app.services.output_validator.repair_prompt_builder import (
    RetryPromptInput,
    build_retry_prompt_input,
)

# ---------------------------------------------------------------------------
# Happy path.
# ---------------------------------------------------------------------------


def test_build_retry_prompt_input_succeeds_with_clean_payload() -> None:
    result = build_retry_prompt_input(
        previous_artifact_content={"summary": "plan failed schema"},
        validation_error={"reason": "missing required field"},
        retry_count=1,
    )
    assert isinstance(result, RetryPromptInput)
    assert result.retry_count == 1
    assert result.previous_artifact_summary == {"summary": "plan failed schema"}
    assert result.validation_error_summary == {"reason": "missing required field"}


def test_retry_prompt_input_is_frozen_dataclass() -> None:
    result = build_retry_prompt_input(
        previous_artifact_content={"summary": "ok"},
        validation_error={"reason": "ok"},
        retry_count=0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.retry_count = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Negative validation.
# ---------------------------------------------------------------------------


def test_build_retry_prompt_input_rejects_negative_retry_count() -> None:
    with pytest.raises(ValueError, match="retry_count"):
        build_retry_prompt_input(
            previous_artifact_content={"summary": "ok"},
            validation_error={"reason": "ok"},
            retry_count=-1,
        )


# ---------------------------------------------------------------------------
# Raw-secret key reject (canonical 21 keys, both surfaces).
# SP55-B3-F-002 fix: sweep ``_PROHIBITED_PAYLOAD_KEYS`` directly instead of a
# hand-written subset; any drift in the canonical set is reflected here.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("forbidden_key", sorted(_PROHIBITED_PAYLOAD_KEYS))
def test_build_retry_prompt_input_rejects_every_prohibited_key_in_previous_artifact(
    forbidden_key: str,
) -> None:
    """Sweep all 21 canonical prohibited keys on the previous-artifact surface."""

    with pytest.raises(ValueError, match="prohibited"):
        build_retry_prompt_input(
            previous_artifact_content={forbidden_key: "hostile-value"},
            validation_error={"reason": "ok"},
            retry_count=0,
        )


@pytest.mark.parametrize("forbidden_key", sorted(_PROHIBITED_PAYLOAD_KEYS))
def test_build_retry_prompt_input_rejects_every_prohibited_key_in_validation_error(
    forbidden_key: str,
) -> None:
    """Sweep all 21 canonical prohibited keys on the validation-error surface."""

    with pytest.raises(ValueError, match="prohibited"):
        build_retry_prompt_input(
            previous_artifact_content={"summary": "ok"},
            validation_error={forbidden_key: "hostile-value"},
            retry_count=0,
        )


def test_build_retry_prompt_input_rejects_prohibited_key_nested() -> None:
    """Recursive scan: prohibited key nested inside a dict must reject too."""

    with pytest.raises(ValueError, match="prohibited"):
        build_retry_prompt_input(
            previous_artifact_content={"details": {"api_key": "sk-hostile"}},
            validation_error={"reason": "ok"},
            retry_count=0,
        )


# ---------------------------------------------------------------------------
# Raw-secret value reject (8 regex patterns).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_value",
    [
        "sk-1234567890abcdef1234567890abcdef",  # openai_api_key
        "sk-ant-abcdefghijklmnopqrstuvwxyz",  # anthropic_api_key
        "ghs_abcdefghijklmnopqrstuvwxyz1234",  # github_installation_token
        "gho_abcdefghijklmnopqrstuvwxyz1234",  # github_oauth_token
        "ghp_abcdefghijklmnopqrstuvwxyz1234",  # github_personal_token
        "tskey-abcdefghijklmnop-abcdefghijklmnop",  # tailscale_auth_key
        "AGE-SECRET-KEY-1ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWX",  # age_private_key
        "-----BEGIN RSA PRIVATE KEY-----",  # pem_private_key
    ],
)
def test_build_retry_prompt_input_rejects_raw_secret_value_patterns(
    raw_value: str,
) -> None:
    with pytest.raises(ValueError):
        build_retry_prompt_input(
            previous_artifact_content={"echoed_raw_response": raw_value},
            validation_error={"reason": "ok"},
            retry_count=0,
        )


# ---------------------------------------------------------------------------
# Cyclic / over-deep reject (defense-in-depth via shared scanner).
# ---------------------------------------------------------------------------


def test_build_retry_prompt_input_rejects_cyclic_payload() -> None:
    cyclic: dict[str, object] = {"x": 1}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError, match="cyclic"):
        build_retry_prompt_input(
            previous_artifact_content=cyclic,
            validation_error={"reason": "ok"},
            retry_count=0,
        )


# ---------------------------------------------------------------------------
# SP55-B3-F-001 fix: nested mutation regression.
# ---------------------------------------------------------------------------


def test_build_retry_prompt_input_deep_copies_previous_artifact_to_prevent_post_construction_tampering() -> None:
    """SP55-B3-F-001 fix: the stored summary must be a deep copy so the caller
    cannot mutate the nested dict / list to smuggle raw secret material into
    the retry prompt after construction."""

    nested_payload: dict[str, object] = {"details": {"clean": "ok"}}
    result = build_retry_prompt_input(
        previous_artifact_content=nested_payload,
        validation_error={"reason": "ok"},
        retry_count=0,
    )
    # Hostile post-construction mutation of the caller's reference.
    details = nested_payload["details"]
    assert isinstance(details, dict)
    details["api_key"] = "sk-late-injection-attempt"
    # The stored retry prompt must NOT reflect the hostile mutation.
    stored_details = result.previous_artifact_summary["details"]
    assert isinstance(stored_details, dict)
    assert "api_key" not in stored_details


def test_build_retry_prompt_input_deep_copies_validation_error_to_prevent_post_construction_tampering() -> None:
    nested_payload: dict[str, object] = {"errors": [{"field": "x"}]}
    result = build_retry_prompt_input(
        previous_artifact_content={"summary": "ok"},
        validation_error=nested_payload,
        retry_count=0,
    )
    errors = nested_payload["errors"]
    assert isinstance(errors, list)
    errors.append({"private_key": "-----BEGIN PRIVATE KEY-----"})
    stored_errors = result.validation_error_summary["errors"]
    assert isinstance(stored_errors, list)
    assert all("private_key" not in entry for entry in stored_errors)


def test_retry_prompt_input_post_init_rejects_direct_construction_with_raw_secret() -> None:
    """SP55-B3-F-001 fix: even direct frozen-dataclass construction (bypassing
    the builder) must trigger the raw-secret scan via ``__post_init__``."""

    with pytest.raises(ValueError, match="prohibited"):
        RetryPromptInput(
            previous_artifact_summary={"api_key": "sk-hostile"},
            validation_error_summary={"reason": "ok"},
            retry_count=0,
        )


def test_retry_prompt_input_post_init_rejects_direct_construction_with_negative_retry() -> None:
    with pytest.raises(ValueError, match="retry_count"):
        RetryPromptInput(
            previous_artifact_summary={"summary": "ok"},
            validation_error_summary={"reason": "ok"},
            retry_count=-1,
        )


# ---------------------------------------------------------------------------
# SP55-B3-R2-F-001 fix: direct construction takes ownership + top-level
# mapping is read-only.
# ---------------------------------------------------------------------------


def test_retry_prompt_input_direct_construction_owns_deep_copy_of_input() -> None:
    """SP55-B3-R2-F-001 fix: direct frozen-dataclass construction (bypassing
    the builder) must still defend against post-construction mutation of the
    caller's reference graph via ``__post_init__`` deep copy."""

    nested_payload: dict[str, object] = {"details": {"clean": "ok"}}
    result = RetryPromptInput(
        previous_artifact_summary=nested_payload,
        validation_error_summary={"reason": "ok"},
        retry_count=0,
    )
    details = nested_payload["details"]
    assert isinstance(details, dict)
    # Hostile late mutation of the caller's reference.
    details["api_key"] = "sk-hostile-late-injection"
    # The stored retry prompt must NOT reflect the hostile mutation.
    stored = result.previous_artifact_summary["details"]
    assert isinstance(stored, dict)
    assert "api_key" not in stored


def test_retry_prompt_input_top_level_mapping_rejects_item_assignment() -> None:
    """SP55-B3-R2-F-001 fix: top-level mapping is wrapped in
    ``MappingProxyType``, so caller cannot ``result.previous_artifact_summary
    ["api_key"] = ...`` to smuggle raw secret material post-construction."""

    result = build_retry_prompt_input(
        previous_artifact_content={"summary": "ok"},
        validation_error={"reason": "ok"},
        retry_count=0,
    )
    with pytest.raises(TypeError):
        result.previous_artifact_summary["api_key"] = "sk-hostile"  # type: ignore[index]
    with pytest.raises(TypeError):
        result.validation_error_summary["api_key"] = "sk-hostile"  # type: ignore[index]


def test_retry_prompt_input_top_level_mapping_rejects_item_deletion() -> None:
    result = build_retry_prompt_input(
        previous_artifact_content={"summary": "ok"},
        validation_error={"reason": "ok"},
        retry_count=0,
    )
    with pytest.raises(TypeError):
        del result.previous_artifact_summary["summary"]  # type: ignore[attr-defined]


def test_retry_prompt_input_as_dict_returns_fresh_copy() -> None:
    """``as_dict()`` provides JSON-serializable plain dicts that are fresh on
    every call; mutating the returned dict must not affect the retained
    internal state (defense-in-depth for the serialization boundary)."""

    result = build_retry_prompt_input(
        previous_artifact_content={"summary": "ok"},
        validation_error={"reason": "ok"},
        retry_count=2,
    )
    snapshot = result.as_dict()
    snapshot["previous_artifact_summary"]["api_key"] = "sk-hostile"
    # Internal state untouched.
    assert "api_key" not in dict(result.previous_artifact_summary)
    # Second call returns a fresh dict.
    snapshot2 = result.as_dict()
    assert "api_key" not in snapshot2["previous_artifact_summary"]
