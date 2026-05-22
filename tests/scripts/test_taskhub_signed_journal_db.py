"""Tests for `scripts.taskhub_signed_journal_db` (SP022-T08 batch 5).

- verify_db_signed_journal_async: tenant-scoped fetch + build_signed_journal_chain
- output dict schema: mode="db" + tenant_id + entry_count + final_hash + tamper_detected
- usage errors: invalid tenant_id / max_entries / expected_final_hash
- expected_final_hash match: tamper_detected=False on match、True on mismatch
- max_entries enforcement
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from scripts.taskhub_signed_journal_db import (
    DEFAULT_MAX_ENTRIES,
    SignedJournalDbUsageError,
    verify_db_signed_journal_async,
)


@dataclass
class _FakeAuditEvent:
    """Minimal AuditEvent mock matching backend.app.db.models.audit_event.AuditEvent fields."""

    id: object
    tenant_id: int
    event_type: str
    event_payload: dict[str, object]
    actor_id: object | None = None
    principal_id: object | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    created_at: datetime | None = None


def _make_event(*, event_type: str = "test_event", payload: dict | None = None) -> _FakeAuditEvent:
    return _FakeAuditEvent(
        id=uuid4(),
        tenant_id=1,
        event_type=event_type,
        event_payload=payload or {"k": "v"},
        created_at=datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC),
    )


def _build_mock_session(audit_events: list[_FakeAuditEvent]) -> MagicMock:
    """Mock AsyncSession that returns audit_events via session.execute(stmt).scalars()."""
    session = MagicMock()
    scalars = MagicMock()
    scalars.__iter__ = lambda self: iter(audit_events)
    result_mock = MagicMock()
    result_mock.scalars = MagicMock(return_value=scalars)
    session.execute = AsyncMock(return_value=result_mock)
    return session


# === verify_db_signed_journal_async tests ===


def test_async_empty_chain_raises_tenant_scope_empty() -> None:
    """Codex PR #90 R3 F-001 fix (P1): audit_events 空 → SignedJournalDbUsageError('tenant_scope_empty').

    旧挙動 (silent tamper_detected=false) は operator が tenant_id をミスタイプして
    存在しない tenant に対して "verified OK" と誤判定する事故を生むため fail-closed。
    """
    session = _build_mock_session([])
    with pytest.raises(SignedJournalDbUsageError) as exc_info:
        asyncio.run(verify_db_signed_journal_async(session, tenant_id=1))
    assert exc_info.value.error_code == "tenant_scope_empty"
    assert "tenant_id=1" in exc_info.value.summary


def test_async_with_events_computes_non_initial_hash() -> None:
    """audit_events 1+ 件 → final_hash != initial_hash + entry_count 反映."""
    events = [_make_event(event_type="t1"), _make_event(event_type="t2")]
    session = _build_mock_session(events)
    result = asyncio.run(verify_db_signed_journal_async(session, tenant_id=1))
    assert result["entry_count"] == 2
    assert result["final_hash"] != "0" * 64
    assert len(result["final_hash"]) == 64
    # hex 形式
    int(result["final_hash"], 16)


def test_async_expected_final_hash_match_no_tamper() -> None:
    """expected_final_hash が computed と一致 → tamper_detected=False."""
    events = [_make_event(event_type="t1")]
    session = _build_mock_session(events)
    # 先に hash を計算
    first = asyncio.run(verify_db_signed_journal_async(session, tenant_id=1))
    expected = first["final_hash"]
    # 再実行 (session を rebuild、deterministic chain) + expected check
    session2 = _build_mock_session(events)
    result = asyncio.run(verify_db_signed_journal_async(
        session2, tenant_id=1, expected_final_hash=expected,
    ))
    assert result["expected_final_hash_match"] is True
    assert result["tamper_detected"] is False


def test_async_expected_final_hash_mismatch_triggers_tamper() -> None:
    """expected_final_hash mismatch → tamper_detected=True."""
    events = [_make_event(event_type="t1")]
    session = _build_mock_session(events)
    fake_expected = "a" * 64
    result = asyncio.run(verify_db_signed_journal_async(
        session, tenant_id=1, expected_final_hash=fake_expected,
    ))
    assert result["expected_final_hash_match"] is False
    assert result["tamper_detected"] is True


def test_async_invalid_tenant_id_raises_usage_error() -> None:
    """tenant_id <= 0 → SignedJournalDbUsageError('invalid_tenant_id')."""
    session = _build_mock_session([])
    with pytest.raises(SignedJournalDbUsageError) as exc_info:
        asyncio.run(verify_db_signed_journal_async(session, tenant_id=0))
    assert exc_info.value.error_code == "invalid_tenant_id"


def test_async_invalid_max_entries_raises_usage_error() -> None:
    """max_entries < 1 → SignedJournalDbUsageError('invalid_max_entries')."""
    session = _build_mock_session([])
    with pytest.raises(SignedJournalDbUsageError) as exc_info:
        asyncio.run(verify_db_signed_journal_async(session, tenant_id=1, max_entries=0))
    assert exc_info.value.error_code == "invalid_max_entries"


def test_async_invalid_expected_final_hash_format_raises_usage_error() -> None:
    """expected_final_hash が 64 chars hex 形式以外 → invalid_expected_final_hash."""
    session = _build_mock_session([])
    with pytest.raises(SignedJournalDbUsageError) as exc_info:
        asyncio.run(verify_db_signed_journal_async(
            session, tenant_id=1, expected_final_hash="not-hex",
        ))
    assert exc_info.value.error_code == "invalid_expected_final_hash"


def test_async_max_entries_exceeded_raises_usage_error() -> None:
    """audit_events count > max_entries → max_entries_exceeded fail-closed."""
    events = [_make_event(event_type=f"t{i}") for i in range(3)]
    session = _build_mock_session(events)  # 3 件 (limit+1 で 3 件取得)
    with pytest.raises(SignedJournalDbUsageError) as exc_info:
        asyncio.run(verify_db_signed_journal_async(session, tenant_id=1, max_entries=2))
    assert exc_info.value.error_code == "max_entries_exceeded"


# === SignedJournalDbUsageError tests ===


def test_usage_error_stderr_message_format() -> None:
    """stderr_message() に error_code + summary が含まれる (operator triage 用)."""
    exc = SignedJournalDbUsageError("test_code", "test summary")
    msg = exc.stderr_message()
    assert "test_code" in msg
    assert "test summary" in msg
    assert msg.startswith("ERROR")


# === CLI dispatch contract tests ===


def test_default_max_entries_constant_is_100k() -> None:
    """DEFAULT_MAX_ENTRIES = 100k (offline mode と一致)."""
    assert DEFAULT_MAX_ENTRIES == 100000


def test_async_rejects_bool_tenant_id() -> None:
    """Codex PR #90 R1 F-001 fix (P2): tenant_id=True (bool) は invalid_tenant_id."""
    session = _build_mock_session([])
    with pytest.raises(SignedJournalDbUsageError) as exc_info:
        asyncio.run(verify_db_signed_journal_async(session, tenant_id=True))  # type: ignore[arg-type]
    assert exc_info.value.error_code == "invalid_tenant_id"


def test_async_rejects_bool_max_entries() -> None:
    """Codex PR #90 R1 F-002 fix (P3): max_entries=True (bool) は invalid_max_entries."""
    session = _build_mock_session([])
    with pytest.raises(SignedJournalDbUsageError) as exc_info:
        asyncio.run(verify_db_signed_journal_async(
            session, tenant_id=1, max_entries=True,  # type: ignore[arg-type]
        ))
    assert exc_info.value.error_code == "invalid_max_entries"


def test_async_rejects_max_entries_exceeding_upper_bound() -> None:
    """Codex PR #90 R1 F-003 fix (P2): max_entries > 100k は max_entries_out_of_range fail-closed."""
    session = _build_mock_session([])
    with pytest.raises(SignedJournalDbUsageError) as exc_info:
        asyncio.run(verify_db_signed_journal_async(
            session, tenant_id=1, max_entries=100_001,
        ))
    assert exc_info.value.error_code == "max_entries_out_of_range"


def test_async_rejects_expected_final_hash_with_trailing_newline() -> None:
    """Codex PR #90 R1 F-004 fix (P2): 末尾改行付き hash は \\Z anchor で reject."""
    session = _build_mock_session([])
    hash_with_newline = ("a" * 64) + "\n"
    with pytest.raises(SignedJournalDbUsageError) as exc_info:
        asyncio.run(verify_db_signed_journal_async(
            session, tenant_id=1, expected_final_hash=hash_with_newline,
        ))
    assert exc_info.value.error_code == "invalid_expected_final_hash"


def test_db_connection_error_redacts_raw_exception_text() -> None:
    """Codex PR #90 R2 F-001 fix (P2): DB exception の raw text (DSN credentials) を user-facing error から除外.

    verify_db_signed_journal が内部で create_async_engine() を呼び connection error を
    SignedJournalDbUsageError に変換するが、DSN URL や password が含まれる Exception text を
    そのまま embed すると credential 漏洩リスク。type(exc).__name__ のみ embed。
    """
    from scripts.taskhub_signed_journal_db import verify_db_signed_journal

    # Codex PR #90 R3 F-004 fix (P3): network-free invalid URL でも raw exc text を verify。
    # 旧 `nonexistent.example` は DNS lookup に依存 (CI resolver settings で flaky)、
    # SQLAlchemy が parse できない garbage scheme で create_async_engine が即時 fail する経路に置換。
    sensitive_url = "garbage-scheme://user:supersecretpassword@host/db"
    with pytest.raises(SignedJournalDbUsageError) as exc_info:
        verify_db_signed_journal(
            tenant_id=1,
            database_url=sensitive_url,
        )
    assert exc_info.value.error_code == "db_connection_error"
    # password を summary に含まない (raw exception text leak 防止)
    assert "supersecretpassword" not in exc_info.value.summary
    # user-facing summary は exception class name のみ embed
    assert "check internal log" in exc_info.value.summary


def test_async_result_has_serializable_dict() -> None:
    """output dict は json.dumps できる (CLI JSON output 前提)."""
    session = _build_mock_session([_make_event()])
    result = asyncio.run(verify_db_signed_journal_async(session, tenant_id=1))
    json_str = json.dumps(result, sort_keys=True)
    parsed = json.loads(json_str)
    assert parsed["mode"] == "db"
    assert parsed["tenant_id"] == 1
