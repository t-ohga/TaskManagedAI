"""SP-027 (ADR-00053): owner gate wiring + schema invariant + enum integrity (no-DB)。"""

from __future__ import annotations

import inspect
from uuid import UUID

import pytest

from backend.app.api.approval_inbox import get_current_actor_id
from backend.app.api.evidence_source_trust import (
    TRUST_AUDIT_PAYLOAD_KEYS,
    build_trust_audit_payload,
    resolve_trust_write,
    set_evidence_source_trust_endpoint,
)
from backend.app.api.me import require_project_owner
from backend.app.db.models.evidence_source import EvidenceSource
from backend.app.schemas.source_trust import EvidenceSourceTrustUpdate

EXPECTED_TRUST_TIERS = {"low", "medium", "high"}


def _dependencies(endpoint: object) -> list[object]:
    signature = inspect.signature(endpoint)  # type: ignore[arg-type]
    return [getattr(param.default, "dependency", None) for param in signature.parameters.values()]


def test_trust_write_uses_owner_gate() -> None:
    deps = _dependencies(set_evidence_source_trust_endpoint)
    assert require_project_owner in deps


def test_trust_write_not_bare_actor() -> None:
    deps = _dependencies(set_evidence_source_trust_endpoint)
    assert get_current_actor_id not in deps


def test_evidence_source_trust_check_contains_all_tiers() -> None:
    sql = next(
        str(c.sqltext)
        for c in EvidenceSource.__table__.constraints
        if getattr(c, "name", None) == "evidence_sources_ck_trust_level"
    )
    for tier in EXPECTED_TRUST_TIERS:
        assert f"'{tier}'" in sql


def test_score_requires_level_check_exists() -> None:
    names = {getattr(c, "name", None) for c in EvidenceSource.__table__.constraints}
    assert "evidence_sources_ck_trust_score_requires_level" in names
    assert "evidence_sources_ck_trust_score_range" in names


def test_update_schema_set_valid() -> None:
    parsed = EvidenceSourceTrustUpdate.model_validate({"trust_level": "high", "trust_score": 0.8})
    assert parsed.trust_level == "high"
    assert parsed.trust_score == 0.8


def test_update_schema_clear_valid() -> None:
    parsed = EvidenceSourceTrustUpdate.model_validate({"trust_level": None, "trust_score": None})
    assert parsed.trust_level is None
    assert parsed.trust_score is None


def test_update_schema_score_without_level_rejected() -> None:
    with pytest.raises(ValueError, match="trust_score requires trust_level"):
        EvidenceSourceTrustUpdate.model_validate({"trust_level": None, "trust_score": 0.5})


def test_update_schema_rejects_extra_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EvidenceSourceTrustUpdate.model_validate({"trust_level": "low", "canonical_url": "x"})


def test_update_schema_rejects_invalid_tier() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EvidenceSourceTrustUpdate.model_validate({"trust_level": "ultra"})


def test_update_schema_rejects_out_of_range_score() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EvidenceSourceTrustUpdate.model_validate({"trust_level": "low", "trust_score": 1.5})


def test_audit_payload_is_exactly_five_allowlist_keys() -> None:
    """Codex adversarial R1 MEDIUM (F-002): audit payload は固定 5-field のみ。"""
    payload = build_trust_audit_payload(
        evidence_source_id=UUID("00000000-0000-4000-8000-000000047006"),
        action="set",
        trust_level="high",
        trust_score=0.9,
        origin="manual",
    )
    assert set(payload.keys()) == TRUST_AUDIT_PAYLOAD_KEYS
    assert set(payload.keys()) == {
        "evidence_source_id",
        "action",
        "trust_level",
        "trust_score",
        "origin",
    }
    # tenant / actor / correlation / timestamp は payload に含めない (専用 column)。
    for forbidden in ("tenant_id", "actor_id", "correlation_id", "trace_id", "timestamp", "domain"):
        assert forbidden not in payload


def test_resolve_trust_write_omitted_score_preserves_existing() -> None:
    """adversarial R2 F-002: level set + score 省略 → 既存 score を保持 (silent loss 防止)。"""
    level, score = resolve_trust_write(
        requested_level="high",
        requested_score=None,
        score_provided=False,
        existing_score=0.95,
    )
    assert level == "high"
    assert score == 0.95


def test_resolve_trust_write_explicit_null_clears_score() -> None:
    level, score = resolve_trust_write(
        requested_level="high",
        requested_score=None,
        score_provided=True,
        existing_score=0.95,
    )
    assert level == "high"
    assert score is None


def test_resolve_trust_write_explicit_score_overrides() -> None:
    level, score = resolve_trust_write(
        requested_level="medium",
        requested_score=0.4,
        score_provided=True,
        existing_score=0.95,
    )
    assert level == "medium"
    assert score == 0.4


def test_resolve_trust_write_clear_level_clears_both() -> None:
    level, score = resolve_trust_write(
        requested_level=None,
        requested_score=None,
        score_provided=False,
        existing_score=0.95,
    )
    assert level is None
    assert score is None
