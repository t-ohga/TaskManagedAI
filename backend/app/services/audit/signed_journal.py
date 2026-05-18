"""Sprint 12 batch 10 (BL-0149 evidence chain): signed journal hash chain.

SP-012 §267-279 spec: tamper-evident append-only audit chain.

Each `AuditEvent` row is hashed with its predecessor's hash to build a chain.
The final hash represents the tamper-evident proof: any historical insertion /
modification / deletion in the chain alters the final hash.

Pure functions (no DB / FS / network). Caller materializes `AuditEvent` rows
in `created_at ASC, id ASC` order and passes the iterable.

invariants:
- canonical JSON encoding (RFC 8785 = JCS) before SHA-256
- NFC UTF-8 normalization (cross-platform stability)
- predecessor hash binding (Merkle-like linear chain)
- empty chain → INITIAL_HASH ("0"×64、convention for genesis state)
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from backend.app.db.models.audit_event import AuditEvent

# Genesis convention: empty chain hash (SHA-256 hex 64 chars of nothing).
# all-zero literal は test fixtures / placeholder と一致しないよう、SHA-256
# canonical empty input (`SHA-256("")`) ではなく、明示的な genesis sentinel
# を使う (空 chain と "1 entry whose previous_hash is something" が区別可能).
SIGNED_JOURNAL_INITIAL_HASH: Final[str] = "0" * 64

# JSON encoding: sorted keys + minimal separators + non-ASCII preserved (NFC
# applied separately for stability across encoding implementations).
_JSON_SEPARATORS: Final[tuple[str, str]] = (",", ":")


@dataclass(frozen=True, slots=True)
class SignedJournalEntry:
    """1 audit event chain link (id, event_type, payload, hash binding).

    `entry_hash` = SHA-256( NFC-UTF8( JCS-canonical-JSON(
      {
        "previous_hash": str,
        "id": str,
        "event_type": str,
        "tenant_id": int,
        "actor_id": str | None,
        "principal_id": str | None,
        "correlation_id": str | None,
        "trace_id": str | None,
        "event_payload": dict,
        "created_at": str | None,
      }
    )))

    `previous_hash` は直前 entry の `entry_hash`. 最初の entry は
    `SIGNED_JOURNAL_INITIAL_HASH` を previous_hash に使用.
    """

    audit_event_id: str  # UUID hex string (server-canonical)
    event_type: str
    previous_hash: str
    entry_hash: str


@dataclass(frozen=True, slots=True)
class SignedJournalChain:
    """An immutable signed journal chain over a sequence of audit events.

    `final_hash` is the last entry's `entry_hash`, or
    `SIGNED_JOURNAL_INITIAL_HASH` if the chain is empty.

    invariant: `len(entries)` == `entry_count`.
    """

    entry_count: int
    final_hash: str
    entries: tuple[SignedJournalEntry, ...]


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    """RFC 8785 canonical JSON + NFC UTF-8 normalize → SHA-256 hex."""
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=_JSON_SEPARATORS,
        ensure_ascii=False,
    )
    normalized = unicodedata.normalize("NFC", canonical)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _serialize_audit_event(
    audit_event: AuditEvent,
    *,
    previous_hash: str,
) -> dict[str, Any]:
    """`AuditEvent` ORM row + previous_hash → canonical-JSON-ready dict.

    SP-012 §267-279 invariant: chain payload includes previous_hash + every
    server-owned field that downstream verifiers care about for tamper
    detection. raw secret / capability token は payload 段階で redact 済前提.
    """
    return {
        "previous_hash": previous_hash,
        "id": str(audit_event.id),
        "event_type": audit_event.event_type,
        "tenant_id": int(audit_event.tenant_id),
        "actor_id": (
            str(audit_event.actor_id) if audit_event.actor_id is not None else None
        ),
        "principal_id": (
            str(audit_event.principal_id)
            if audit_event.principal_id is not None
            else None
        ),
        "correlation_id": audit_event.correlation_id,
        "trace_id": audit_event.trace_id,
        "event_payload": audit_event.event_payload,
        "created_at": (
            audit_event.created_at.isoformat() if audit_event.created_at is not None else None
        ),
    }


def build_signed_journal_chain(
    audit_events: Iterable[AuditEvent],
) -> SignedJournalChain:
    """Build a signed journal chain over the given `audit_events` (ordered ASC).

    pure function. Caller materializes ORM rows in stable order
    (`created_at ASC, id ASC`) before calling. Returns empty chain
    (final_hash = INITIAL_HASH) when the input is empty.

    Tamper detection: re-running this function on the *current* DB state
    must yield the same `final_hash` as the prior snapshot. Insert / modify /
    delete in any historical position alters the final hash.
    """
    entries: list[SignedJournalEntry] = []
    previous_hash = SIGNED_JOURNAL_INITIAL_HASH

    for audit_event in audit_events:
        chain_payload = _serialize_audit_event(audit_event, previous_hash=previous_hash)
        entry_hash = _canonical_json_sha256(chain_payload)
        entries.append(
            SignedJournalEntry(
                audit_event_id=str(audit_event.id),
                event_type=audit_event.event_type,
                previous_hash=previous_hash,
                entry_hash=entry_hash,
            )
        )
        previous_hash = entry_hash

    final_hash = previous_hash  # = INITIAL_HASH if no entries were added
    return SignedJournalChain(
        entry_count=len(entries),
        final_hash=final_hash,
        entries=tuple(entries),
    )


def verify_signed_journal_chain(
    chain: SignedJournalChain,
    audit_events: Iterable[AuditEvent],
) -> bool:
    """Re-compute the chain over `audit_events` and compare with `chain.final_hash`.

    Returns True iff the recomputed chain matches `chain` element-wise and
    final_hash equality holds. Any insertion / modification / deletion in
    `audit_events` (versus the original ordering when `chain` was built)
    yields False.

    NOTE: this is a pure verifier; caller is responsible for fetching audit
    events in the same canonical order used at build time
    (`created_at ASC, id ASC`).
    """
    recomputed = build_signed_journal_chain(audit_events)
    if recomputed.entry_count != chain.entry_count:
        return False
    if recomputed.final_hash != chain.final_hash:
        return False
    for original, replay in zip(chain.entries, recomputed.entries, strict=True):
        if original.audit_event_id != replay.audit_event_id:
            return False
        if original.event_type != replay.event_type:
            return False
        if original.previous_hash != replay.previous_hash:
            return False
        if original.entry_hash != replay.entry_hash:
            return False
    return True


__all__ = [
    "SIGNED_JOURNAL_INITIAL_HASH",
    "SignedJournalChain",
    "SignedJournalEntry",
    "build_signed_journal_chain",
    "verify_signed_journal_chain",
]
