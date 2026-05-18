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
import math
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC
from typing import Any, Final

from backend.app.db.models.audit_event import AuditEvent
from backend.app.services.research.evidence_set_hash import _jcs_canonical_json

# Genesis convention: empty chain hash (SHA-256 hex 64 chars of nothing).
# all-zero literal は test fixtures / placeholder と一致しないよう、SHA-256
# canonical empty input (`SHA-256("")`) ではなく、明示的な genesis sentinel
# を使う (空 chain と "1 entry whose previous_hash is something" が区別可能).
SIGNED_JOURNAL_INITIAL_HASH: Final[str] = "0" * 64


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


def _reject_nan_inf(value: object, *, path: str = "$") -> None:
    """F-PR66-005 P2 adopt: NaN / Infinity を fail-closed reject.

    Python `json.dumps` は default で NaN / Infinity を allow (`allow_nan=True`)、
    かつ RFC 8785 number canonicalization と完全一致しない. JCS spec
    違反となる非有限 float を hash 前に物理 reject し、verifier 間で
    deterministic な hash を保証する.
    """
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            msg = f"non-finite float not permitted in signed journal payload: {path}={value!r}"
            raise ValueError(msg)
    elif isinstance(value, dict):
        for k, v in value.items():
            _reject_nan_inf(v, path=f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _reject_nan_inf(v, path=f"{path}[{i}]")


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    """RFC 8785 canonical JSON + NFC UTF-8 normalize → SHA-256 hex.

    F-PR66-005 P2 adopt: non-finite float (NaN / Infinity) は hash 前に reject.
    F-PR66-006 P2 adopt: **real JCS serializer** (evidence_set_hash._jcs_canonical_json)
    を使用. Python `json.dumps(sort_keys=True)` は RFC 8785 と byte-stream
    一致しないケースあり (`1.0` / `-0.0` / `1e-6` 等の number canonicalization、
    object key の UTF-16 code unit ordering)、JCS-compliant verifier との
    portability を担保するため existing JCS impl を再利用.
    """
    _reject_nan_inf(payload)
    canonical = _jcs_canonical_json(payload)
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

    F-PR66-002 P2 adopt: unflushed row (`created_at=None`) を reject. ORM の
    `server_default` で commit 後 timestamp が割当されるが、commit 前に hash
    すると persist 後の hash と不一致になり verifier から tampered と誤判定
    される. 必ず flush/refresh 済の row を渡す invariant を fail-closed で担保.

    F-PR66-004 P2 adopt: `created_at` を UTC に normalize してから isoformat 化.
    異なる接続 TimeZone (postgresql `TimeZone` session setting) でも同一 instant
    が同 string になり hash 不変.
    """
    if audit_event.created_at is None:
        msg = (
            f"signed journal requires AuditEvent.created_at to be persisted "
            f"(audit_event_id={audit_event.id}): unflushed row hashes "
            f"differently from the committed snapshot, breaking tamper "
            f"detection. Flush/refresh the row before chain construction."
        )
        raise ValueError(msg)
    # F-PR66-004 P2 adopt: UTC normalize (timezone-aware datetime に対し
    # astimezone(UTC) で offset 統一、naive な場合は UTC として扱う).
    created_at_utc = audit_event.created_at
    if created_at_utc.tzinfo is None:
        # naive datetime は UTC 扱い (DB は timestamptz、ORM 経由で読むと通常
        # tzinfo が付くが、defensive に handle).
        created_at_utc = created_at_utc.replace(tzinfo=UTC)
    else:
        created_at_utc = created_at_utc.astimezone(UTC)

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
        "created_at": created_at_utc.isoformat(),
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
    # F-PR66-001 P2 adopt: malformed snapshot (entries が entry_count と矛盾) を
    # ValueError ではなく False で返す. zip(..., strict=True) は両 sequence 長
    # 不一致で raise するため、事前 len check で False 経路を guarantee.
    if len(chain.entries) != chain.entry_count:
        return False
    if len(recomputed.entries) != chain.entry_count:
        return False
    for original, replay in zip(chain.entries, recomputed.entries, strict=False):
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
