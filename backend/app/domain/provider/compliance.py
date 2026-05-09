from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.domain.artifact.data_class import (
    DATA_CLASS_ORDINAL as PAYLOAD_DATA_CLASS_ORDINAL,
)
from backend.app.domain.artifact.data_class import (
    PayloadDataClass,
    data_class_ordinal,
)

ComplianceReasonCode = Literal[
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
]

ALL_COMPLIANCE_REASON_CODES: tuple[ComplianceReasonCode, ...] = (
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

ComplianceDecisionKind = Literal["allow", "deny", "downgrade"]
ZdrEligible = Literal["yes", "no", "conditional", "n/a"]
Retention = Literal["0d", "30d", "90d", "unverified"]
RetentionPolicy = Retention
TrainingUse = Literal["no", "yes", "unverified"]
Region = Literal["verified", "unverified"]
RegionOrDataTransfer = Region
PlanRequired = Literal["api_tier", "business", "enterprise", "none"]
ConditionStatus = Literal["verified", "unverified", "not_applicable"]


class ComplianceMatrixMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(..., min_length=1, max_length=128)
    last_updated_at: str
    description: str = Field(..., min_length=1)

    @field_validator("last_updated_at")
    @classmethod
    def _last_updated_at_must_be_iso_date(cls, value: str) -> str:
        return _ensure_iso_date(value, field_name="last_updated_at")


class ComplianceMatrixEntry(BaseModel):
    """Provider Compliance Matrix row.

    p0_policy_note is governance-only free text. It must never be used as a
    runtime policy input. Matrix version is stored once in [meta].version, not
    on each row.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(..., min_length=1, max_length=128)
    api_or_feature: str = Field(..., min_length=1, max_length=128)
    zdr_eligible: ZdrEligible
    retention: Retention
    training_use: TrainingUse
    region_or_data_transfer: Region
    subprocessor_or_doc_url: str = Field(..., min_length=1)
    plan_required: PlanRequired
    allowed_data_class: PayloadDataClass
    condition_status: ConditionStatus
    p0_policy_note: str
    last_verified_at: str

    @field_validator("last_verified_at")
    @classmethod
    def _last_verified_at_must_be_iso_date(cls, value: str) -> str:
        return _ensure_iso_date(value, field_name="last_verified_at")


class ComplianceMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    meta: ComplianceMatrixMeta
    entries: list[ComplianceMatrixEntry] = Field(..., min_length=1)

    @property
    def matrix_version(self) -> str:
        return self.meta.version


class ComplianceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: ComplianceDecisionKind
    reason_code: ComplianceReasonCode
    allowed_data_class: PayloadDataClass | None
    effective_allowed_data_class: PayloadDataClass | None
    payload_data_class: PayloadDataClass | None
    provider_compliance_matrix_version: str = Field(..., min_length=1, max_length=128)


def is_payload_data_class(value: object) -> bool:
    return isinstance(value, str) and value in PAYLOAD_DATA_CLASS_ORDINAL


def _ensure_iso_date(value: str, *, field_name: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO calendar date.") from exc
    return value


__all__ = [
    "ALL_COMPLIANCE_REASON_CODES",
    "PAYLOAD_DATA_CLASS_ORDINAL",
    "ComplianceDecision",
    "ComplianceDecisionKind",
    "ComplianceMatrix",
    "ComplianceMatrixEntry",
    "ComplianceMatrixMeta",
    "ComplianceReasonCode",
    "ConditionStatus",
    "PlanRequired",
    "Region",
    "RegionOrDataTransfer",
    "Retention",
    "RetentionPolicy",
    "TrainingUse",
    "ZdrEligible",
    "data_class_ordinal",
    "is_payload_data_class",
]

