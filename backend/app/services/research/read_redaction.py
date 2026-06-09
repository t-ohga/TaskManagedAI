"""SP-032 (ADR-00052) Codex adversarial R3 F-CRITICAL: conflict group / domain trust の read
serializer を **共有 choke point** に集約する。

API 層 (conflict_groups / domain_trust) と research-advanced summary service の両方が本 module を
通すことで、title / resolution_note / domain / rationale に secret-shaped 値が (直書き / legacy /
将来 scanner drift で) 残っていても全 read 経路で redaction される (write reject の defense-in-depth)。
"""

from __future__ import annotations

from backend.app.db.models.conflict_group import ConflictGroup
from backend.app.db.models.domain_trust import DomainTrustRegistry
from backend.app.schemas.conflict_group import ConflictGroupRead
from backend.app.schemas.domain_trust import DomainTrustRead
from backend.app.services.security.secret_text_scan import redact_if_secret


def to_conflict_group_read(group: ConflictGroup) -> ConflictGroupRead:
    """ConflictGroup -> ConflictGroupRead (title / resolution_note を redaction)。"""
    read = ConflictGroupRead.model_validate(group)
    return read.model_copy(
        update={
            "title": redact_if_secret(read.title) or read.title,
            "resolution_note": redact_if_secret(read.resolution_note),
        }
    )


def to_domain_trust_read(entry: DomainTrustRegistry) -> DomainTrustRead:
    """DomainTrustRegistry -> DomainTrustRead (domain / rationale を redaction)。"""
    read = DomainTrustRead.model_validate(entry)
    return read.model_copy(
        update={
            "domain": redact_if_secret(read.domain) or read.domain,
            "rationale": redact_if_secret(read.rationale),
        }
    )


def redact_domain(domain: str) -> str:
    """audit payload 等に載せる domain を redaction (tainted legacy/direct-write 値の再永続化防止)。"""
    return redact_if_secret(domain) or domain


__all__ = ["redact_domain", "to_conflict_group_read", "to_domain_trust_read"]
