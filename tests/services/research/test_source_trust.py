from __future__ import annotations

from uuid import UUID

from backend.app.services.research.source_trust import resolve_effective_source_trust

_SID = UUID("00000000-0000-4000-8000-000000046001")


def test_manual_override_wins() -> None:
    eff = resolve_effective_source_trust(
        evidence_source_id=_SID,
        manual_trust_level="high",
        manual_trust_score=0.9,
        domain_tier="low",  # ignored because manual is set
        domain="example.com",
    )
    assert eff.origin == "manual"
    assert eff.trust_level == "high"
    assert eff.trust_score == 0.9
    assert eff.domain is None
    assert eff.match_type == "none"


def test_domain_fallback_when_no_manual() -> None:
    eff = resolve_effective_source_trust(
        evidence_source_id=_SID,
        manual_trust_level=None,
        manual_trust_score=None,
        domain_tier="medium",
        domain="example.com",
    )
    assert eff.origin == "domain"
    assert eff.trust_level == "medium"
    assert eff.trust_score is None  # domain origin は常に score null (F-005)
    assert eff.domain == "example.com"
    assert eff.match_type == "exact"


def test_none_when_domain_unregistered() -> None:
    eff = resolve_effective_source_trust(
        evidence_source_id=_SID,
        manual_trust_level=None,
        manual_trust_score=None,
        domain_tier=None,
        domain="example.com",
    )
    assert eff.origin == "none"
    assert eff.trust_level is None
    assert eff.match_type == "none"
    assert eff.domain == "example.com"


def test_invalid_when_domain_unresolvable() -> None:
    eff = resolve_effective_source_trust(
        evidence_source_id=_SID,
        manual_trust_level=None,
        manual_trust_score=None,
        domain_tier=None,
        domain=None,  # domain_from_url が None (malformed / secret-shaped)
    )
    assert eff.origin == "invalid"
    assert eff.trust_level is None
    assert eff.domain is None
    assert eff.match_type == "invalid"
