from __future__ import annotations

from pathlib import Path
from typing import Any, get_args
from uuid import UUID

import pytest

from backend.app.domain.provider.compliance import (
    ALL_COMPLIANCE_REASON_CODES,
    PAYLOAD_DATA_CLASS_ORDINAL,
    ComplianceMatrixEntry,
    ComplianceReasonCode,
)
from backend.app.domain.provider.request import ProviderMessage, ProviderRequest
from backend.app.services.providers.compliance_gate import ComplianceGate
from backend.app.services.providers.matrix_loader import (
    ComplianceMatrix as LoadedComplianceMatrix,
)
from backend.app.services.providers.matrix_loader import load_compliance_matrix

RUN_ID = UUID("00000000-0000-4000-8000-000000005702")

_EXPECTED_REASON_CODES = (
    "payload_data_class_unset",
    "payload_data_class_exceeds_allowed",
    "effective_allowed_data_class_exceeded",
    "zdr_ineligible",
    "training_use_not_no",
    "condition_unverified",
    "retention_unverified",
    "region_unverified",
    "plan_unverified",
    "provider_not_in_matrix",
    "provider_request_preflight_violation",
    "budget_exceeded",
    "allow",
)


def _entry(**overrides: Any) -> ComplianceMatrixEntry:
    payload: dict[str, Any] = {
        "provider": "mock",
        "api_or_feature": "mock",
        "zdr_eligible": "yes",
        "retention": "0d",
        "training_use": "no",
        "region_or_data_transfer": "verified",
        "subprocessor_or_doc_url": "repository-docs",
        "plan_required": "enterprise",
        "allowed_data_class": "confidential",
        "condition_status": "not_applicable",
        "p0_policy_note": "test row",
        "last_verified_at": "2026-05-09",
    }
    payload.update(overrides)
    return ComplianceMatrixEntry.model_validate(payload)


def _gate(
    entry: ComplianceMatrixEntry | None = None,
    *,
    matrix_version: str = "pcm-v1",
) -> ComplianceGate:
    entries = {} if entry is None else {(entry.provider, entry.api_or_feature): entry}
    matrix = LoadedComplianceMatrix(entries, matrix_version=matrix_version)
    return ComplianceGate(matrix_loader=matrix, audit_emitter=None)


def _provider_request(
    *,
    payload_data_class: object = "internal",
    provider: str = "mock",
    api_or_feature: str = "mock",
    matrix_version: str = "pcm-v1",
) -> ProviderRequest:
    return ProviderRequest.model_construct(
        tenant_id=1,
        run_id=RUN_ID,
        provider=provider,
        api_or_feature=api_or_feature,
        model_resolved="mock-model",
        messages=[ProviderMessage.model_construct(role="user", content="hello")],
        structured_output_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
        },
        payload_data_class=payload_data_class,
        provider_compliance_matrix_version=matrix_version,
        max_tokens=256,
        temperature=0,
        safety_settings={"mode": "test"},
        secret_capability_token=None,
    )


def test_reason_code_literal_set_matches_provider_compliance_rule() -> None:
    assert tuple(get_args(ComplianceReasonCode)) == _EXPECTED_REASON_CODES
    assert ALL_COMPLIANCE_REASON_CODES == _EXPECTED_REASON_CODES


def test_payload_data_class_ordinal_matches_frozen_rule() -> None:
    assert PAYLOAD_DATA_CLASS_ORDINAL == {
        "public": 0,
        "internal": 1,
        "confidential": 2,
        "pii": 3,
    }


def test_payload_data_class_ordinal_is_canonical_identity() -> None:
    """R3-F-001 (R4): F-005 drift 防止 identity test。

    Sprint 4 Batch 2 canonical `backend.app.domain.artifact.data_class.DATA_CLASS_ORDINAL`
    と Sprint 5 Batch 2 provider compliance side `PAYLOAD_DATA_CLASS_ORDINAL` が
    `is` で同一 object であることを保証する。compliance.py 側で別 dict を再定義した場合に
    drift が test で検出される。
    """
    from backend.app.domain.artifact.data_class import DATA_CLASS_ORDINAL

    assert PAYLOAD_DATA_CLASS_ORDINAL is DATA_CLASS_ORDINAL


@pytest.mark.parametrize(
    ("reason_code", "entry", "provider_request"),
    [
        ("payload_data_class_unset", _entry(), _provider_request(payload_data_class=None)),
        (
            "payload_data_class_exceeds_allowed",
            _entry(allowed_data_class="internal"),
            _provider_request(payload_data_class="confidential"),
        ),
        (
            "effective_allowed_data_class_exceeded",
            _entry(retention="unverified", allowed_data_class="confidential"),
            _provider_request(payload_data_class="confidential"),
        ),
        (
            "zdr_ineligible",
            _entry(zdr_eligible="no", allowed_data_class="confidential"),
            _provider_request(payload_data_class="internal"),
        ),
        (
            "training_use_not_no",
            _entry(training_use="unverified", allowed_data_class="confidential"),
            _provider_request(payload_data_class="internal"),
        ),
        (
            "condition_unverified",
            _entry(
                zdr_eligible="conditional",
                condition_status="unverified",
                allowed_data_class="confidential",
            ),
            _provider_request(payload_data_class="internal"),
        ),
        (
            "retention_unverified",
            _entry(retention="unverified", allowed_data_class="confidential"),
            _provider_request(payload_data_class="internal"),
        ),
        (
            "region_unverified",
            _entry(region_or_data_transfer="unverified", allowed_data_class="confidential"),
            _provider_request(payload_data_class="internal"),
        ),
        (
            "plan_unverified",
            _entry(plan_required="none", allowed_data_class="confidential"),
            _provider_request(payload_data_class="internal"),
        ),
        ("provider_not_in_matrix", None, _provider_request(payload_data_class="internal")),
        ("allow", _entry(), _provider_request(payload_data_class="internal")),
    ],
)
def test_compliance_gate_evaluate_triggers_reason_codes(
    reason_code: str,
    entry: ComplianceMatrixEntry | None,
    provider_request: ProviderRequest,
) -> None:
    decision = _gate(entry).evaluate(provider_request)

    assert decision.reason_code == reason_code


@pytest.mark.parametrize(
    ("entry", "payload_data_class", "effective_allowed_data_class", "reason_code"),
    [
        (_entry(training_use="yes"), "public", "public", "training_use_not_no"),
        (_entry(zdr_eligible="no"), "public", "public", "zdr_ineligible"),
        (_entry(zdr_eligible="n/a"), "public", "public", "zdr_ineligible"),
        (
            _entry(zdr_eligible="conditional", condition_status="unverified"),
            "internal",
            "internal",
            "condition_unverified",
        ),
        (_entry(retention="unverified"), "internal", "internal", "retention_unverified"),
        (
            _entry(region_or_data_transfer="unverified"),
            "internal",
            "internal",
            "region_unverified",
        ),
        (_entry(plan_required="none"), "internal", "internal", "plan_unverified"),
    ],
)
def test_effective_allowed_data_class_downgrade_paths(
    entry: ComplianceMatrixEntry,
    payload_data_class: str,
    effective_allowed_data_class: str,
    reason_code: str,
) -> None:
    decision = _gate(entry).evaluate(_provider_request(payload_data_class=payload_data_class))

    assert decision.decision == "downgrade"
    assert decision.reason_code == reason_code
    assert decision.effective_allowed_data_class == effective_allowed_data_class


def test_zdr_eligible_na_denies_internal_or_higher_fail_closed() -> None:
    decision = _gate(_entry(zdr_eligible="n/a")).evaluate(
        _provider_request(payload_data_class="internal")
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "zdr_ineligible"


def test_matrix_version_mismatch_denies_stale_request() -> None:
    decision = _gate(_entry(), matrix_version="pcm-v2").evaluate(
        _provider_request(payload_data_class="internal", matrix_version="pcm-v1")
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "provider_not_in_matrix"
    assert decision.provider_compliance_matrix_version == "pcm-v2"


def test_ordinal_comparison_denies_payload_above_matrix_raw_allowed() -> None:
    decision = _gate(_entry(allowed_data_class="internal")).evaluate(
        _provider_request(payload_data_class="confidential")
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "payload_data_class_exceeds_allowed"
    assert decision.allowed_data_class == "internal"
    assert decision.effective_allowed_data_class == "internal"


def test_allow_path_preserves_matrix_version() -> None:
    decision = _gate(_entry(), matrix_version="pcm-v1").evaluate(
        _provider_request(payload_data_class="internal")
    )

    assert decision.decision == "allow"
    assert decision.reason_code == "allow"
    assert decision.provider_compliance_matrix_version == "pcm-v1"


def test_compliance_matrix_entry_rejects_row_matrix_version() -> None:
    payload = _entry().model_dump(mode="json")
    payload["provider_compliance_matrix_version"] = "pcm-v1"

    with pytest.raises(ValueError, match="provider_compliance_matrix_version"):
        ComplianceMatrixEntry.model_validate(payload)


def test_load_compliance_matrix_rejects_unknown_column(tmp_path: Path) -> None:
    matrix_path = tmp_path / "provider_compliance.toml"
    matrix_path.write_text(
        """
[meta]
version = "pcm-v1"
last_updated_at = "2026-05-09"
description = "test matrix"

[[entries]]
provider = "mock"
api_or_feature = "mock"
zdr_eligible = "yes"
retention = "0d"
training_use = "no"
region_or_data_transfer = "verified"
subprocessor_or_doc_url = "repository-docs"
plan_required = "enterprise"
allowed_data_class = "confidential"
condition_status = "not_applicable"
p0_policy_note = "test"
last_verified_at = "2026-05-09"
unknown_column = "must fail"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown_column"):
        load_compliance_matrix(matrix_path)


def test_load_compliance_matrix_rejects_row_matrix_version(tmp_path: Path) -> None:
    matrix_path = tmp_path / "provider_compliance.toml"
    matrix_path.write_text(
        """
[meta]
version = "pcm-v1"
last_updated_at = "2026-05-09"
description = "test matrix"

[[entries]]
provider = "mock"
api_or_feature = "mock"
zdr_eligible = "yes"
retention = "0d"
training_use = "no"
region_or_data_transfer = "verified"
subprocessor_or_doc_url = "repository-docs"
plan_required = "enterprise"
allowed_data_class = "confidential"
condition_status = "not_applicable"
p0_policy_note = "test"
last_verified_at = "2026-05-09"
provider_compliance_matrix_version = "pcm-v1"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="provider_compliance_matrix_version"):
        load_compliance_matrix(matrix_path)


def test_load_compliance_matrix_keeps_meta_version_separate(tmp_path: Path) -> None:
    matrix_path = tmp_path / "provider_compliance.toml"
    matrix_path.write_text(
        """
[meta]
version = "pcm-v1"
last_updated_at = "2026-05-09"
description = "test matrix"

[[entries]]
provider = "mock"
api_or_feature = "mock"
zdr_eligible = "yes"
retention = "0d"
training_use = "no"
region_or_data_transfer = "verified"
subprocessor_or_doc_url = "repository-docs"
plan_required = "enterprise"
allowed_data_class = "confidential"
condition_status = "not_applicable"
p0_policy_note = "test"
last_verified_at = "2026-05-09"
""".strip(),
        encoding="utf-8",
    )

    matrix = load_compliance_matrix(matrix_path)

    assert matrix.matrix_version == "pcm-v1"
    assert not hasattr(matrix[("mock", "mock")], "provider_compliance_matrix_version")


def test_config_provider_compliance_toml_loads_p0_five_entries() -> None:
    matrix = load_compliance_matrix(Path("config/provider_compliance.toml"))

    assert matrix.matrix_version == "v2026.05.09-p0-skeleton"
    assert set(matrix) == {
        ("openai", "responses"),
        ("anthropic", "messages"),
        ("anthropic", "batches"),
        ("gemini", "generate_content"),
        ("mock", "mock"),
    }
    assert len(matrix) == 5
    assert matrix[("gemini", "generate_content")].allowed_data_class == "public"
    assert matrix[("mock", "mock")].allowed_data_class == "pii"

