"""Offline JSONL signed journal verification (SP022-T08 batch 1).

`backend/app/services/audit/signed_journal.py` の pure function を wrap、
actual DB session 不要で JSONL 経由 audit_events を verify する CLI helper.

`AuditEvent` ORM は import される (signed_journal.py 内 module-level import の
transitivity)、但し CLI 起動時に actual DB connection は確立しない (offline mode)。
Phase 2 で pure signed_journal_core.py 抽出を判断 (R2-F-001 adopt、本 batch 1 carry-over).

CLI invariants:
- strict structural schema (R1-F-006 + R1-F-010 + R1-F-016 + R1-F-017 adopt)
- extra fields reject + nullable required + timezone-aware datetime 必須
- NaN/Infinity reject (R1-F-004 adopt、`json.loads(parse_constant=...)`)
- error message redaction (R1-F-005 adopt、raw payload value leak 防止)
- DoS 防御: max_entries + max_line_bytes range validation (R1-F-002 + R1-F-015 adopt)
- exit code: 0 PASS / 1 tamper / 2 usage error (R1-F-003 adopt)
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

# pure function pipeline import — backend.app.db chain も transitively import
# されるが、actual DB session は確立しない (R2-F-001 adopt)
from backend.app.services.audit.signed_journal import (
    SIGNED_JOURNAL_INITIAL_HASH,
    build_signed_journal_chain,
)

if TYPE_CHECKING:
    from backend.app.db.models.audit_event import AuditEvent

DEFAULT_MAX_ENTRIES = 100000
MIN_MAX_ENTRIES = 1
DEFAULT_MAX_LINE_BYTES = 65536  # 64 KB
MIN_MAX_LINE_BYTES = 1024  # 1 KB
MAX_MAX_LINE_BYTES = 1048576  # 1 MB

EXPECTED_FINAL_HASH_REGEX = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_NON_NULL_FIELDS = frozenset({
    "id", "event_type", "tenant_id", "event_payload", "created_at",
})
_REQUIRED_NULLABLE_FIELDS = frozenset({
    "actor_id", "principal_id", "correlation_id", "trace_id",
})
_ALL_REQUIRED_FIELDS = _REQUIRED_NON_NULL_FIELDS | _REQUIRED_NULLABLE_FIELDS

ReasonCode = Literal[
    "signed_journal_offline_verified",
    "signed_journal_offline_hash_computed",
    "signed_journal_offline_input_not_found",
    "signed_journal_offline_input_too_large",
    "signed_journal_offline_jsonl_schema_invalid",
    "signed_journal_offline_jsonl_non_finite_float",
    "signed_journal_offline_expected_hash_invalid",
    "signed_journal_offline_expected_hash_mismatch",
    "signed_journal_offline_empty_chain",
    "signed_journal_offline_arg_out_of_range",
]


class SignedJournalUsageError(Exception):
    """Maps to exit 2 (CLI usage error / schema invalid / arg out of range).

    R1-F-003 + R1-F-005 adopt: external-facing sanitized error。
    `reason_code` + `line_no` + `field` のみを stderr に出す、raw payload value は持たない。
    """

    def __init__(
        self, reason_code: ReasonCode, *,
        line_no: int | None = None, field: str | None = None, detail: str = "",
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.line_no = line_no
        self.field = field
        self.detail = detail  # short, safe explanation (no raw value)

    def stderr_message(self) -> str:
        parts = [f"ERROR reason_code={self.reason_code}"]
        if self.line_no is not None:
            parts.append(f"line_no={self.line_no}")
        if self.field is not None:
            parts.append(f"field={self.field}")
        if self.detail:
            parts.append(f"detail={self.detail}")
        return " ".join(parts)


class SignedJournalTamperError(Exception):
    """Maps to exit 1 (explicit tamper detection、`--expected-final-hash` mismatch)."""


@dataclasses.dataclass(frozen=True)
class AuditEventLike:
    """ORM-free AuditEvent mirror for offline signed journal verification.

    R1-F-001 adopt: signed_journal.py `_serialize_audit_event` が要求する
    全 attribute (id / event_type / tenant_id / actor_id / principal_id /
    correlation_id / trace_id / event_payload / created_at) を持つ duck-typed
    dataclass。
    """

    id: str  # UUID hex string
    event_type: str
    tenant_id: int
    actor_id: str | None
    principal_id: str | None
    correlation_id: str | None
    trace_id: str | None
    event_payload: dict[str, Any]
    created_at: datetime


def _reject_non_finite(value: str) -> Any:
    """Used as `json.loads(parse_constant=...)`. NaN / Infinity / -Infinity は raise.

    R1-F-004 adopt: json.loads は default で NaN/Infinity を許容するため、
    parse_constant で reject する。
    """
    del value  # value is the constant token (e.g., "NaN"); we reject regardless
    msg = "non-finite float not permitted in event_payload (NaN/Infinity)"
    raise SignedJournalUsageError(
        "signed_journal_offline_jsonl_non_finite_float",
        detail=msg,
    )


def _validate_max_entries(n: int) -> int:
    if not (MIN_MAX_ENTRIES <= n <= DEFAULT_MAX_ENTRIES):
        raise SignedJournalUsageError(
            "signed_journal_offline_arg_out_of_range",
            field="--max-entries",
            detail=f"out of range [{MIN_MAX_ENTRIES}, {DEFAULT_MAX_ENTRIES}]",
        )
    return n


def _validate_max_line_bytes(n: int) -> int:
    if not (MIN_MAX_LINE_BYTES <= n <= MAX_MAX_LINE_BYTES):
        raise SignedJournalUsageError(
            "signed_journal_offline_arg_out_of_range",
            field="--max-line-bytes",
            detail=f"out of range [{MIN_MAX_LINE_BYTES}, {MAX_MAX_LINE_BYTES}]",
        )
    return n


def _validate_expected_final_hash(s: str | None) -> str | None:
    if s is None:
        return None
    if not EXPECTED_FINAL_HASH_REGEX.fullmatch(s):
        raise SignedJournalUsageError(
            "signed_journal_offline_expected_hash_invalid",
            field="--expected-final-hash",
            detail="must match ^[0-9a-f]{64}$ (lowercase hex)",
        )
    return s


def _parse_jsonl_line(line: str, line_no: int) -> AuditEventLike:
    """JSONL 1 行 → AuditEventLike. schema 違反は SignedJournalUsageError raise."""
    try:
        # R1-F-004 adopt: parse_constant で NaN/Infinity reject
        data = json.loads(line, parse_constant=_reject_non_finite)
    except SignedJournalUsageError:
        raise
    except json.JSONDecodeError:
        # R1-F-005 adopt: raw line を message に含めない
        raise SignedJournalUsageError(
            "signed_journal_offline_jsonl_schema_invalid",
            line_no=line_no, detail="invalid JSON",
        ) from None
    if not isinstance(data, dict):
        raise SignedJournalUsageError(
            "signed_journal_offline_jsonl_schema_invalid",
            line_no=line_no, detail="top-level must be JSON object",
        )

    # R1-F-017 adopt: extra fields reject
    extra = set(data.keys()) - _ALL_REQUIRED_FIELDS
    if extra:
        raise SignedJournalUsageError(
            "signed_journal_offline_jsonl_schema_invalid",
            line_no=line_no,
            field=sorted(extra)[0],  # first extra field name
            detail=f"unexpected field(s): {sorted(extra)}",
        )

    # R1-F-006 adopt: 全 required nullable も欠落 reject
    missing = _ALL_REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise SignedJournalUsageError(
            "signed_journal_offline_jsonl_schema_invalid",
            line_no=line_no,
            field=sorted(missing)[0],
            detail=f"missing required field(s): {sorted(missing)}",
        )

    # type validation
    if not isinstance(data["id"], str) or not data["id"]:
        raise SignedJournalUsageError(
            "signed_journal_offline_jsonl_schema_invalid",
            line_no=line_no, field="id",
            detail="must be non-empty string",
        )
    if not isinstance(data["event_type"], str) or not data["event_type"]:
        raise SignedJournalUsageError(
            "signed_journal_offline_jsonl_schema_invalid",
            line_no=line_no, field="event_type",
            detail="must be non-empty string",
        )
    if not isinstance(data["tenant_id"], int) or isinstance(data["tenant_id"], bool) \
            or data["tenant_id"] < 0:
        raise SignedJournalUsageError(
            "signed_journal_offline_jsonl_schema_invalid",
            line_no=line_no, field="tenant_id",
            detail="must be non-negative int",
        )
    if not isinstance(data["event_payload"], dict):
        raise SignedJournalUsageError(
            "signed_journal_offline_jsonl_schema_invalid",
            line_no=line_no, field="event_payload",
            detail="must be JSON object",
        )
    if not isinstance(data["created_at"], str):
        raise SignedJournalUsageError(
            "signed_journal_offline_jsonl_schema_invalid",
            line_no=line_no, field="created_at",
            detail="must be ISO 8601 string",
        )
    # R1-F-010 adopt: timezone-aware 必須
    try:
        created_at = datetime.fromisoformat(data["created_at"])
    except ValueError:
        raise SignedJournalUsageError(
            "signed_journal_offline_jsonl_schema_invalid",
            line_no=line_no, field="created_at",
            detail="invalid ISO 8601 datetime",
        ) from None
    if created_at.tzinfo is None:
        raise SignedJournalUsageError(
            "signed_journal_offline_jsonl_schema_invalid",
            line_no=line_no, field="created_at",
            detail="naive datetime not permitted; timezone-aware required",
        )

    def _opt_str(key: str) -> str | None:
        v = data.get(key)
        if v is None:
            return None
        if not isinstance(v, str):
            raise SignedJournalUsageError(
                "signed_journal_offline_jsonl_schema_invalid",
                line_no=line_no, field=key,
                detail="must be string or null",
            )
        return v

    return AuditEventLike(
        id=data["id"],
        event_type=data["event_type"],
        tenant_id=data["tenant_id"],
        actor_id=_opt_str("actor_id"),
        principal_id=_opt_str("principal_id"),
        correlation_id=_opt_str("correlation_id"),
        trace_id=_opt_str("trace_id"),
        event_payload=data["event_payload"],
        created_at=created_at,
    )


def _iter_jsonl_lines(
    input_path: str, max_entries: int, max_line_bytes: int,
) -> Iterator[AuditEventLike]:
    """Stream JSONL file (or stdin if path == '-'). Skip blank lines.

    R1-F-002 adopt: per-line byte size + max_entries で DoS 防御。
    """
    source: Any
    close_after = False
    if input_path == "-":
        source = sys.stdin
    else:
        p = Path(input_path)
        if not p.exists():
            raise SignedJournalUsageError(
                "signed_journal_offline_input_not_found",
                field="--input", detail=f"file not found: {input_path}",
            )
        try:
            source = p.open("r", encoding="utf-8")
        except OSError:
            raise SignedJournalUsageError(
                "signed_journal_offline_input_not_found",
                field="--input", detail=f"cannot open: {input_path}",
            ) from None
        close_after = True
    try:
        count = 0
        for line_no, line in enumerate(source, start=1):
            # R1-F-002 adopt: bytes 長で line size validation
            line_bytes = line.encode("utf-8")
            if len(line_bytes) > max_line_bytes:
                raise SignedJournalUsageError(
                    "signed_journal_offline_input_too_large",
                    line_no=line_no, field="--max-line-bytes",
                    detail=f"line size {len(line_bytes)} > {max_line_bytes}",
                )
            stripped = line.strip()
            if not stripped:
                continue
            count += 1
            if count > max_entries:
                raise SignedJournalUsageError(
                    "signed_journal_offline_input_too_large",
                    line_no=line_no, field="--max-entries",
                    detail=f"input exceeds max_entries={max_entries}",
                )
            yield _parse_jsonl_line(stripped, line_no)
    finally:
        if close_after:
            source.close()


def verify_jsonl_signed_journal(
    input_path: str,
    *,
    expected_final_hash: str | None = None,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
) -> dict[str, Any]:
    """Build chain from JSONL, optionally compare with expected_final_hash.

    Returns result dict. Raises SignedJournalUsageError (exit 2),
    SignedJournalTamperError (exit 1) as appropriate.

    R1-F-012 adopt: empty_chain は warnings array に追加、reason_code は
    exit 判定の主理由 (mismatch 時は mismatch 優先)。
    R1-F-014 adopt: expected_final_hash 未指定時は verification_performed=false
    + reason_code = signed_journal_offline_hash_computed。
    """
    _validate_max_entries(max_entries)
    _validate_max_line_bytes(max_line_bytes)
    _validate_expected_final_hash(expected_final_hash)

    events = list(_iter_jsonl_lines(input_path, max_entries, max_line_bytes))
    try:
        # AuditEventLike is duck-typed-compatible with AuditEvent (signed_journal
        # `_serialize_audit_event` only accesses attributes by name)。type cast
        # で静的型を満たしつつ runtime は duck typing で機能する。
        chain = build_signed_journal_chain(cast("list[AuditEvent]", events))
    except ValueError as exc:
        # R1-F-003 adopt: build 中の ValueError (NaN/Inf reject 等) は input invalidity
        # → exit 2 schema_invalid (raw exc message は出さない)
        raise SignedJournalUsageError(
            "signed_journal_offline_jsonl_schema_invalid",
            detail=f"chain build rejected input: {type(exc).__name__}",
        ) from None

    warnings: list[str] = []
    if chain.entry_count == 0:
        warnings.append("signed_journal_offline_empty_chain")

    result: dict[str, Any] = {
        "mode": "signed-journal-offline",
        "entry_count": chain.entry_count,
        "final_hash": chain.final_hash,
        "verification_performed": expected_final_hash is not None,
        "warnings": warnings,
        "ignored_fields": [],  # extra fields は reject 設計のため常に empty (R1-F-017 adopt)
    }

    if expected_final_hash is not None:
        result["expected_final_hash"] = expected_final_hash
        verified = chain.final_hash == expected_final_hash
        result["verified"] = verified
        result["tamper_detected"] = not verified
        if verified:
            result["reason_code"] = "signed_journal_offline_verified"
        else:
            result["reason_code"] = "signed_journal_offline_expected_hash_mismatch"
    else:
        result["reason_code"] = "signed_journal_offline_hash_computed"

    return result


__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_LINE_BYTES",
    "EXPECTED_FINAL_HASH_REGEX",
    "MAX_MAX_LINE_BYTES",
    "MIN_MAX_ENTRIES",
    "MIN_MAX_LINE_BYTES",
    "SIGNED_JOURNAL_INITIAL_HASH",
    "AuditEventLike",
    "ReasonCode",
    "SignedJournalTamperError",
    "SignedJournalUsageError",
    "verify_jsonl_signed_journal",
]
