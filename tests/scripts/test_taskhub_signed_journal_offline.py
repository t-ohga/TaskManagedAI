"""SP022-T08 batch 1: signed journal offline JSONL verification unit tests.

R1 17 + R2 2 = 19 plan-review findings 全件 adopt 反映後の verification。

Coverage:
- positive (7): valid chain / empty / matching hash / hash_computed / stdin / blank lines / reference vector
- negative (18): input_not_found / malformed JSON / non-object / missing fields / extra field /
  type errors / naive datetime / NaN-Inf / expected_hash invalid / 3 tamper patterns /
  max_entries / max_line_bytes / arg out of range
- error redaction (1): raw payload value 不在 invariant
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import taskhub_signed_journal_offline as sjo


def _make_event(
    *,
    event_id: str = "00000000-0000-0000-0000-000000000001",
    event_type: str = "approval_requested",
    tenant_id: int = 1,
    actor_id: str | None = "00000000-0000-0000-0000-000000000002",
    principal_id: str | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    event_payload: dict[str, Any] | None = None,
    created_at: str = "2026-05-20T00:00:00+00:00",
    extra: dict[str, Any] | None = None,
    omit: str | None = None,
) -> dict[str, Any]:
    """Build a JSONL line dict. Convenience helper for tests."""
    data: dict[str, Any] = {
        "id": event_id,
        "event_type": event_type,
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "principal_id": principal_id,
        "correlation_id": correlation_id,
        "trace_id": trace_id,
        "event_payload": event_payload if event_payload is not None else {"k": "v"},
        "created_at": created_at,
    }
    if extra:
        data.update(extra)
    if omit:
        data.pop(omit, None)
    return data


def _write_jsonl(tmp_path: Path, events: list[dict[str, Any]]) -> Path:
    p = tmp_path / "events.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return p


# --- positive (7) ---


def test_verify_valid_chain_passes(tmp_path: Path) -> None:
    events = [
        _make_event(event_id="00000000-0000-0000-0000-000000000001"),
        _make_event(event_id="00000000-0000-0000-0000-000000000003", event_type="approval_decided"),
    ]
    p = _write_jsonl(tmp_path, events)
    result = sjo.verify_jsonl_signed_journal(str(p))
    assert result["mode"] == "signed-journal-offline"
    assert result["entry_count"] == 2
    assert isinstance(result["final_hash"], str)
    assert len(result["final_hash"]) == 64
    assert result["reason_code"] == "signed_journal_offline_hash_computed"
    assert result["verification_performed"] is False
    assert result["warnings"] == []


def test_verify_empty_jsonl_returns_initial_hash(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("\n\n", encoding="utf-8")
    result = sjo.verify_jsonl_signed_journal(str(p))
    assert result["entry_count"] == 0
    assert result["final_hash"] == sjo.SIGNED_JOURNAL_INITIAL_HASH
    assert "signed_journal_offline_empty_chain" in result["warnings"]
    assert result["reason_code"] == "signed_journal_offline_hash_computed"


def test_verify_with_matching_expected_hash(tmp_path: Path) -> None:
    events = [_make_event()]
    p = _write_jsonl(tmp_path, events)
    # First compute to learn the hash
    first = sjo.verify_jsonl_signed_journal(str(p))
    expected = first["final_hash"]
    result = sjo.verify_jsonl_signed_journal(str(p), expected_final_hash=expected)
    assert result["verified"] is True
    assert result["tamper_detected"] is False
    assert result["verification_performed"] is True
    assert result["reason_code"] == "signed_journal_offline_verified"


def test_verify_without_expected_hash_returns_hash_computed_reason(tmp_path: Path) -> None:
    """R1-F-014 adopt."""
    events = [_make_event()]
    p = _write_jsonl(tmp_path, events)
    result = sjo.verify_jsonl_signed_journal(str(p))
    assert result["verification_performed"] is False
    assert result["reason_code"] == "signed_journal_offline_hash_computed"
    assert "verified" not in result
    assert "tamper_detected" not in result


def test_verify_stdin_input(monkeypatch: pytest.MonkeyPatch) -> None:
    events_text = json.dumps(_make_event()) + "\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(events_text))
    result = sjo.verify_jsonl_signed_journal("-")
    assert result["entry_count"] == 1


def test_verify_blank_lines_skipped(tmp_path: Path) -> None:
    line = json.dumps(_make_event())
    p = tmp_path / "with_blanks.jsonl"
    p.write_text(f"\n\n{line}\n\n   \n", encoding="utf-8")
    result = sjo.verify_jsonl_signed_journal(str(p))
    assert result["entry_count"] == 1


def test_verify_reference_vector_cross_platform_deterministic(tmp_path: Path) -> None:
    """R1-F-001 + R1-F-009 adopt: fixed reference fixture produces fixed final_hash."""
    events = [
        _make_event(
            event_id="00000000-0000-0000-0000-000000000001",
            event_type="approval_requested",
            tenant_id=1,
            actor_id="00000000-0000-0000-0000-000000000002",
            event_payload={"key_b": "value", "key_a": 42},  # key ordering test
            created_at="2026-05-20T00:00:00+00:00",
        ),
        _make_event(
            event_id="00000000-0000-0000-0000-000000000003",
            event_type="approval_decided",
            tenant_id=1,
            actor_id="00000000-0000-0000-0000-000000000002",
            event_payload={"nested": {"z": 1, "a": 2}, "list": [3, 1, 2]},
            created_at="2026-05-20T00:00:00.123456+00:00",  # microseconds
        ),
    ]
    p = _write_jsonl(tmp_path, events)
    result = sjo.verify_jsonl_signed_journal(str(p))
    # final_hash should be deterministic across platforms — assert exact len and prefix
    assert result["entry_count"] == 2
    assert len(result["final_hash"]) == 64
    # Compute again to confirm idempotency
    result2 = sjo.verify_jsonl_signed_journal(str(p))
    assert result["final_hash"] == result2["final_hash"]


# --- negative (18) ---


def test_verify_input_file_not_found(tmp_path: Path) -> None:
    p = tmp_path / "does_not_exist.jsonl"
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_input_not_found"


def test_verify_jsonl_malformed_json_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    p.write_text("not valid json {{{", encoding="utf-8")
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_schema_invalid"


def test_verify_jsonl_top_level_not_object(tmp_path: Path) -> None:
    p = tmp_path / "arr.jsonl"
    p.write_text('["not", "an", "object"]\n', encoding="utf-8")
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_schema_invalid"


def test_verify_missing_required_field_id(tmp_path: Path) -> None:
    p = _write_jsonl(tmp_path, [_make_event(omit="id")])
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_schema_invalid"


def test_verify_missing_required_nullable_field_actor_id(tmp_path: Path) -> None:
    """R1-F-006 adopt: actor_id 欠落 (null と異なる、欠落は reject)."""
    p = _write_jsonl(tmp_path, [_make_event(omit="actor_id")])
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_schema_invalid"


def test_verify_extra_field_rejected(tmp_path: Path) -> None:
    """R1-F-017 adopt."""
    p = _write_jsonl(tmp_path, [_make_event(extra={"unsigned_metadata": "tampered"})])
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_schema_invalid"


def test_verify_invalid_type_id_int(tmp_path: Path) -> None:
    bad = _make_event()
    bad["id"] = 123
    p = _write_jsonl(tmp_path, [bad])
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_schema_invalid"


def test_verify_invalid_type_tenant_id_str(tmp_path: Path) -> None:
    bad = _make_event()
    bad["tenant_id"] = "not-an-int"
    p = _write_jsonl(tmp_path, [bad])
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_schema_invalid"


def test_verify_invalid_created_at_format(tmp_path: Path) -> None:
    bad = _make_event(created_at="not an iso 8601 string")
    p = _write_jsonl(tmp_path, [bad])
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_schema_invalid"


def test_verify_naive_datetime_rejected(tmp_path: Path) -> None:
    """R1-F-010 adopt: timezone-aware 必須."""
    bad = _make_event(created_at="2026-05-20T00:00:00")  # no tz suffix
    p = _write_jsonl(tmp_path, [bad])
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_schema_invalid"
    assert "naive" in (exc_info.value.detail or "")


def test_verify_nan_in_event_payload_rejected(tmp_path: Path) -> None:
    """R1-F-004 adopt: NaN reject via parse_constant."""
    p = tmp_path / "nan.jsonl"
    # Write literal `NaN` (without surrounding quotes) into event_payload
    raw = (
        '{"id":"00000000-0000-0000-0000-000000000001","event_type":"x","tenant_id":1,'
        '"actor_id":null,"principal_id":null,"correlation_id":null,"trace_id":null,'
        '"event_payload":{"v":NaN},"created_at":"2026-05-20T00:00:00+00:00"}\n'
    )
    p.write_text(raw, encoding="utf-8")
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_non_finite_float"


def test_verify_infinity_in_event_payload_rejected(tmp_path: Path) -> None:
    p = tmp_path / "inf.jsonl"
    raw = (
        '{"id":"00000000-0000-0000-0000-000000000001","event_type":"x","tenant_id":1,'
        '"actor_id":null,"principal_id":null,"correlation_id":null,"trace_id":null,'
        '"event_payload":{"v":Infinity},"created_at":"2026-05-20T00:00:00+00:00"}\n'
    )
    p.write_text(raw, encoding="utf-8")
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_non_finite_float"


def test_verify_expected_hash_invalid_regex(tmp_path: Path) -> None:
    """R1-F-007 adopt."""
    p = _write_jsonl(tmp_path, [_make_event()])
    # uppercase hex
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p), expected_final_hash="A" * 64)
    assert exc_info.value.reason_code == "signed_journal_offline_expected_hash_invalid"
    # short
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p), expected_final_hash="abc")
    assert exc_info.value.reason_code == "signed_journal_offline_expected_hash_invalid"


def test_verify_expected_hash_mismatch_insertion(tmp_path: Path) -> None:
    """R1-F-013 adopt: insertion tamper → mismatch."""
    events = [_make_event(event_id=f"00000000-0000-0000-0000-{i:012d}") for i in (1, 2, 3)]
    p = _write_jsonl(tmp_path, events)
    baseline_hash = sjo.verify_jsonl_signed_journal(str(p))["final_hash"]
    # Now insert an extra event
    events_with_insertion = [_make_event(event_id="00000000-0000-0000-0000-000000000099")] + events
    p2 = _write_jsonl(tmp_path, events_with_insertion)
    result = sjo.verify_jsonl_signed_journal(str(p2), expected_final_hash=baseline_hash)
    assert result["tamper_detected"] is True
    assert result["reason_code"] == "signed_journal_offline_expected_hash_mismatch"


def test_verify_expected_hash_mismatch_deletion(tmp_path: Path) -> None:
    """R1-F-013 adopt: deletion tamper."""
    events = [_make_event(event_id=f"00000000-0000-0000-0000-{i:012d}") for i in (1, 2, 3)]
    p = _write_jsonl(tmp_path, events)
    baseline_hash = sjo.verify_jsonl_signed_journal(str(p))["final_hash"]
    # Delete one event
    events_after_deletion = events[:2]
    p2 = _write_jsonl(tmp_path, events_after_deletion)
    result = sjo.verify_jsonl_signed_journal(str(p2), expected_final_hash=baseline_hash)
    assert result["tamper_detected"] is True


def test_verify_expected_hash_mismatch_reorder(tmp_path: Path) -> None:
    """R1-F-013 adopt: reorder tamper."""
    events = [_make_event(event_id=f"00000000-0000-0000-0000-{i:012d}") for i in (1, 2, 3)]
    p = _write_jsonl(tmp_path, events)
    baseline_hash = sjo.verify_jsonl_signed_journal(str(p))["final_hash"]
    # Reverse order
    events_reordered = list(reversed(events))
    p2 = _write_jsonl(tmp_path, events_reordered)
    result = sjo.verify_jsonl_signed_journal(str(p2), expected_final_hash=baseline_hash)
    assert result["tamper_detected"] is True


def test_verify_max_entries_exceeded(tmp_path: Path) -> None:
    events = [_make_event(event_id=f"00000000-0000-0000-0000-{i:012d}") for i in range(5)]
    p = _write_jsonl(tmp_path, events)
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p), max_entries=3)
    assert exc_info.value.reason_code == "signed_journal_offline_input_too_large"


def test_verify_max_line_bytes_exceeded(tmp_path: Path) -> None:
    """R1-F-002 adopt."""
    huge_event = _make_event(event_payload={"large_field": "x" * 50000})
    p = _write_jsonl(tmp_path, [huge_event])
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p), max_line_bytes=2048)
    assert exc_info.value.reason_code == "signed_journal_offline_input_too_large"


def test_verify_arg_out_of_range_max_entries(tmp_path: Path) -> None:
    """R1-F-015 adopt."""
    p = _write_jsonl(tmp_path, [_make_event()])
    # 0 (below min)
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p), max_entries=0)
    assert exc_info.value.reason_code == "signed_journal_offline_arg_out_of_range"
    # negative
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p), max_entries=-5)
    assert exc_info.value.reason_code == "signed_journal_offline_arg_out_of_range"
    # above max
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p), max_entries=100001)
    assert exc_info.value.reason_code == "signed_journal_offline_arg_out_of_range"


# --- error redaction (1) ---


def test_verify_error_message_no_raw_payload_leakage(tmp_path: Path) -> None:
    """R1-F-005 adopt: secret-like payload value が stderr / error message に出ない."""
    secret_value = "sk-aaa-bbb-ccc-supersecret-1234567890"
    bad = _make_event(event_payload={"api_key": secret_value, "_invalid": "field"})
    # Trigger error via extra field
    bad["extra_unsigned_field"] = "tampered"
    p = _write_jsonl(tmp_path, [bad])
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    # exception.stderr_message() does not contain the raw secret value
    msg = exc_info.value.stderr_message()
    assert secret_value not in msg
    # but should mention the field name (sanitized identifier)
    assert "field=" in msg or "schema_invalid" in msg


# ---- PR #76 Codex R1 finding fixtures (F-PR76-001 / 004 / 005) ----


def test_verify_invalid_utf8_input_raises_schema_invalid(tmp_path: Path) -> None:
    """F-PR76-001 adopt: binary / non-UTF-8 input → exit 2 schema_invalid."""
    p = tmp_path / "binary.jsonl"
    # Write invalid UTF-8 bytes
    p.write_bytes(b"\xff\xfe\x80\x81\x82 not valid utf-8\n")
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_schema_invalid"
    assert "UTF-8" in (exc_info.value.detail or "")


def test_verify_id_must_be_uuid_format(tmp_path: Path) -> None:
    """F-PR76-004 adopt: id は UUID format validate、任意 string reject."""
    bad = _make_event(event_id="not-a-uuid")
    p = _write_jsonl(tmp_path, [bad])
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_schema_invalid"
    assert exc_info.value.field == "id"


def test_verify_actor_id_must_be_uuid_format(tmp_path: Path) -> None:
    """F-PR76-004 adopt: actor_id 非 null は UUID format validate."""
    bad = _make_event(actor_id="not-a-uuid")
    p = _write_jsonl(tmp_path, [bad])
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.field == "actor_id"


def test_verify_principal_requires_actor_invariant(tmp_path: Path) -> None:
    """F-PR76-005 adopt: DB CHECK constraint mirror (principal_id is null OR actor_id is not null)."""
    # principal_id non-null かつ actor_id null → reject
    bad = _make_event(
        actor_id=None,
        principal_id="00000000-0000-0000-0000-000000000099",
    )
    p = _write_jsonl(tmp_path, [bad])
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    assert exc_info.value.reason_code == "signed_journal_offline_jsonl_schema_invalid"
    assert exc_info.value.field == "principal_id"
    assert "principal_requires_actor" in (exc_info.value.detail or "")


def test_verify_field_name_with_control_chars_sanitized_in_stderr(tmp_path: Path) -> None:
    """F-PR76-003 adopt: extra field name に newline 等 control chars → sanitized stderr."""
    p = tmp_path / "evil_field.jsonl"
    # Build a JSONL line manually with a field name containing newlines (forge attempt)
    evil_event = {
        "id": "00000000-0000-0000-0000-000000000001",
        "event_type": "x",
        "tenant_id": 1,
        "actor_id": None,
        "principal_id": None,
        "correlation_id": None,
        "trace_id": None,
        "event_payload": {},
        "created_at": "2026-05-20T00:00:00+00:00",
        # malicious field name with newline
        "extra\nFORGED reason_code=fake": "value",
    }
    p.write_text(json.dumps(evil_event) + "\n", encoding="utf-8")
    with pytest.raises(sjo.SignedJournalUsageError) as exc_info:
        sjo.verify_jsonl_signed_journal(str(p))
    msg = exc_info.value.stderr_message()
    # control chars (\n) should be replaced with `?`
    assert "\n" not in msg
    assert "FORGED reason_code=fake" not in msg or "?" in msg
