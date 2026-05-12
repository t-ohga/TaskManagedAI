"""Input Trust Layer: ``payload_data_class`` pre-computation (Sprint 5.5 BL-0066).

``payload_data_class`` は **request / artifact metadata から事前算出** する。
caller / API endpoint / Server Action / ProviderAdapter から
``payload_data_class`` を直接指定する経路は **signature レベルで物理削除**
されている (``PayloadClassificationInput`` が ``payload_data_class`` field
を露出させず、``extra="forbid"`` で any 余剰 field を schema reject)。

ProviderAdapter (Sprint 5) は事前算出値を **読むだけ** で再算出しない
(`rules/provider-compliance.md` §4 + `rules/server-owned-boundary.md` §1
invariant 継続)。本 module は data class ordinal (ADR-00010 §4) に従って
field hints の上限を計算する fail-closed な classifier。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.artifact.data_class import (
    DATA_CLASS_ORDINAL,
    PayloadDataClass,
)

ContentSensitivityHint = Literal[
    "public",
    "internal",
    "confidential",
    "pii",
]

ClassificationReasonCode = Literal[
    "explicit_pii_hint",
    "explicit_confidential_hint",
    "explicit_internal_hint",
    "external_origin_default_internal",
    "internal_origin_default_public",
]


class PayloadClassificationInput(BaseModel):
    """Caller-facing classification input.

    NOTE: ``payload_data_class`` is intentionally absent — calling code may
    NOT supply a pre-decided classification. Any incoming field outside the
    declared set (``content_sensitivity_hints``, ``contains_pii_markers``,
    ``contains_confidential_markers``, ``external_origin``) is rejected by
    ``extra="forbid"`` (caller-supplied path physically removed at
    signature level, ``rules/server-owned-boundary.md`` §1).
    """

    model_config = ConfigDict(extra="forbid")

    content_sensitivity_hints: list[ContentSensitivityHint] = Field(
        default_factory=list,
        max_length=16,
    )
    contains_pii_markers: bool = False
    contains_confidential_markers: bool = False
    external_origin: bool = False


@dataclass(frozen=True)
class PayloadClassificationResult:
    """Server-computed classification (immutable)."""

    payload_data_class: PayloadDataClass
    reason_codes: tuple[ClassificationReasonCode, ...]


def _max_class(values: tuple[PayloadDataClass, ...]) -> PayloadDataClass:
    ordered = sorted(values, key=lambda v: DATA_CLASS_ORDINAL[v])
    return ordered[-1]


def classify_payload_data_class(
    payload: PayloadClassificationInput,
) -> PayloadClassificationResult:
    """Compute the ``payload_data_class`` from server-side signals only.

    The computation is fail-closed (always returns a defined enum value)
    and uses the canonical ordinal ``public < internal < confidential <
    pii`` (ADR-00010 §4). The highest signal wins; the reason codes record
    every signal that contributed.
    """

    reasons: list[ClassificationReasonCode] = []
    candidates: list[PayloadDataClass] = []

    if payload.contains_pii_markers:
        candidates.append("pii")
        reasons.append("explicit_pii_hint")
    if payload.contains_confidential_markers:
        candidates.append("confidential")
        reasons.append("explicit_confidential_hint")

    for hint in payload.content_sensitivity_hints:
        if hint == "pii":
            candidates.append("pii")
            reasons.append("explicit_pii_hint")
        elif hint == "confidential":
            candidates.append("confidential")
            reasons.append("explicit_confidential_hint")
        elif hint == "internal":
            candidates.append("internal")
            reasons.append("explicit_internal_hint")
        # 'public' hint contributes no upper bound, only a baseline.

    if not candidates:
        if payload.external_origin:
            return PayloadClassificationResult(
                payload_data_class="internal",
                reason_codes=("external_origin_default_internal",),
            )
        return PayloadClassificationResult(
            payload_data_class="public",
            reason_codes=("internal_origin_default_public",),
        )

    deduped: list[ClassificationReasonCode] = []
    for code in reasons:
        if code not in deduped:
            deduped.append(code)

    return PayloadClassificationResult(
        payload_data_class=_max_class(tuple(candidates)),
        reason_codes=tuple(deduped),
    )


__all__ = [
    "ClassificationReasonCode",
    "ContentSensitivityHint",
    "PayloadClassificationInput",
    "PayloadClassificationResult",
    "classify_payload_data_class",
]
