"""Sprint 11.5 batch 3c (BL-0139 + BL-0156): AuditExporter tests.

DB integration 不要 (mock AsyncSession). 確認項目:
- export row に raw secret pattern が含まれば row 単位 reject (AC-HARD-02 trace)
- atomic write (tempfile + rename)、partial file 残らない
- 3 別 data class dimension (payload_data_class / allowed_data_class /
  effective_allowed_data_class) を top-level field に抽出 (BL-0156)
- tenant_id boundary
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from backend.app.services.audit.exporter import (
    AuditExporter,
    AuditExportSummary,
    _build_export_row,
)

_TENANT_ID = 1


def _mock_audit_event(
    *,
    event_id: UUID | None = None,
    event_type: str = "test_event",
    payload: dict | None = None,
    actor_id: UUID | None = None,
    principal_id: UUID | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    created_at: datetime | None = None,
    tenant_id: int = _TENANT_ID,
) -> MagicMock:
    ev = MagicMock()
    ev.id = event_id or uuid4()
    ev.tenant_id = tenant_id
    ev.event_type = event_type
    ev.event_payload = payload or {}
    ev.actor_id = actor_id
    ev.principal_id = principal_id
    ev.correlation_id = correlation_id
    ev.trace_id = trace_id
    ev.created_at = created_at or datetime.now(tz=UTC)
    return ev


def _build_evaluator(events: list[MagicMock]) -> tuple[AuditExporter, MagicMock]:
    """mock session + AuditExporter (with mocked _fetch_events + tenant_context bypass)."""

    session = MagicMock()
    svc = AuditExporter(session)
    svc._ensure_tenant_context = AsyncMock(return_value=None)  # noqa: SLF001
    svc._fetch_events = AsyncMock(return_value=events)  # noqa: SLF001
    return svc, session


def test_build_export_row_extracts_data_class_dimensions() -> None:
    """BL-0156: payload に含まれる 3 別 data class dimension を top-level に抽出."""

    event = _mock_audit_event(
        payload={
            "payload_data_class": "internal",
            "allowed_data_class": "confidential",
            "effective_allowed_data_class": "internal",
            "request_id": "req-123",
        }
    )
    row = _build_export_row(event)
    assert row["payload_data_class"] == "internal"
    assert row["allowed_data_class"] == "confidential"
    assert row["effective_allowed_data_class"] == "internal"
    # 元 payload 内にも残っている (top-level も payload 内も両方)
    assert row["payload"]["payload_data_class"] == "internal"


def test_build_export_row_no_aggregate_data_class_field() -> None:
    """BL-0156: 合算の `data_class` 単一 field は出力されない (3 別 dimension 厳格)."""

    event = _mock_audit_event(payload={"payload_data_class": "public"})
    row = _build_export_row(event)
    # `data_class` (合算) ではなく `payload_data_class` (個別) のみ
    assert "data_class" not in row
    assert row["payload_data_class"] == "public"


def test_build_export_row_missing_data_class_does_not_add_keys() -> None:
    """data class dimension fields が payload になければ top-level にも追加しない."""

    event = _mock_audit_event(payload={"request_id": "req-456"})
    row = _build_export_row(event)
    assert "payload_data_class" not in row
    assert "allowed_data_class" not in row
    assert "effective_allowed_data_class" not in row


@pytest.mark.asyncio
async def test_export_jsonl_writes_clean_rows_to_file(tmp_path: Path) -> None:
    """clean audit_events を JSON Lines に export、rows_exported count 正確."""

    events = [
        _mock_audit_event(
            event_type="approval_pending",
            payload={"payload_data_class": "internal", "approval_id": "ap-1"},
        ),
        _mock_audit_event(
            event_type="run_completed",
            payload={"payload_data_class": "public", "run_id": "r-1"},
        ),
    ]
    svc, _session = _build_evaluator(events)
    output = tmp_path / "audit-export.jsonl"

    summary = await svc.export_jsonl(
        tenant_id=_TENANT_ID,
        start=datetime.now(tz=UTC) - timedelta(days=1),
        end=datetime.now(tz=UTC) + timedelta(days=1),
        output_path=output,
    )
    assert summary.rows_exported == 2
    assert summary.rows_rejected_raw_secret == 0
    assert summary.error_message is None
    assert output.exists()

    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    row1 = json.loads(lines[0])
    assert row1["event_type"] == "approval_pending"
    assert row1["payload_data_class"] == "internal"


@pytest.mark.asyncio
async def test_export_jsonl_rejects_raw_secret_row(tmp_path: Path) -> None:
    """raw secret pattern 含む row を reject、rows_rejected カウントに記録 (AC-HARD-02)."""

    events = [
        _mock_audit_event(
            event_type="suspicious_event",
            payload={"leaked_value": "sk-fakeButLooksReal0123456789ABCDEF"},
        ),
        _mock_audit_event(event_type="clean_event", payload={"request_id": "r-1"}),
    ]
    svc, _session = _build_evaluator(events)
    output = tmp_path / "audit-export.jsonl"

    summary = await svc.export_jsonl(
        tenant_id=_TENANT_ID,
        start=datetime.now(tz=UTC) - timedelta(days=1),
        end=datetime.now(tz=UTC) + timedelta(days=1),
        output_path=output,
    )
    assert summary.rows_exported == 1
    assert summary.rows_rejected_raw_secret == 1

    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["event_type"] == "clean_event"


@pytest.mark.asyncio
async def test_export_jsonl_rejects_prohibited_key(tmp_path: Path) -> None:
    """prohibited key (`api_key` 等) も reject (AC-HARD-02 enforcement)."""

    events = [
        _mock_audit_event(
            event_type="suspicious_event",
            payload={"api_key": "anything"},
        ),
    ]
    svc, _session = _build_evaluator(events)
    output = tmp_path / "audit-export.jsonl"

    summary = await svc.export_jsonl(
        tenant_id=_TENANT_ID,
        start=datetime.now(tz=UTC) - timedelta(days=1),
        end=datetime.now(tz=UTC) + timedelta(days=1),
        output_path=output,
    )
    assert summary.rows_exported == 0
    assert summary.rows_rejected_raw_secret == 1


@pytest.mark.asyncio
async def test_export_jsonl_no_partial_file_on_failure(tmp_path: Path) -> None:
    """atomic write: 失敗時に partial file を残さない (tempfile cleanup)."""

    events = [_mock_audit_event(event_type="ok", payload={"x": "y"})]
    svc, _session = _build_evaluator(events)
    output = tmp_path / "audit-export.jsonl"

    # 強制的に rename failure を発生させる (tempfile.replace を mock).
    from unittest.mock import patch

    with patch("pathlib.Path.replace", side_effect=OSError("simulated rename failure")):
        summary = await svc.export_jsonl(
            tenant_id=_TENANT_ID,
            start=datetime.now(tz=UTC) - timedelta(days=1),
            end=datetime.now(tz=UTC) + timedelta(days=1),
            output_path=output,
        )
    assert summary.error_message == "OSError"
    # output file は失敗時に存在しないこと、tmp file もcleanupされていること
    assert not output.exists()
    # tmp dir に残骸 .audit-export-*.jsonl.tmp が存在しない
    tmp_files = list(tmp_path.glob(".audit-export-*.jsonl.tmp"))  # noqa: ASYNC240
    assert tmp_files == []


@pytest.mark.asyncio
async def test_export_jsonl_empty_events(tmp_path: Path) -> None:
    """events が空でも export file は作成される (0 row)."""

    svc, _session = _build_evaluator([])
    output = tmp_path / "audit-export.jsonl"

    summary = await svc.export_jsonl(
        tenant_id=_TENANT_ID,
        start=datetime.now(tz=UTC) - timedelta(days=1),
        end=datetime.now(tz=UTC) + timedelta(days=1),
        output_path=output,
    )
    assert summary.rows_exported == 0
    assert summary.rows_rejected_raw_secret == 0
    assert summary.error_message is None
    assert output.exists()
    assert output.read_text(encoding="utf-8") == ""


@pytest.mark.asyncio
async def test_export_jsonl_payload_with_nested_uuid_not_falsely_rejected(
    tmp_path: Path,
) -> None:
    """code-reviewer R1 MEDIUM adopt: payload nested UUID/datetime を
    JSON-roundtrip normalize、`assert_no_raw_secret` の type strict 制約
    で誤 reject しないこと verify.
    """

    approval_uuid = uuid4()
    events = [
        _mock_audit_event(
            event_type="clean_event_with_nested_uuid",
            payload={
                "approval_id": approval_uuid,  # UUID (nested)
                "created_at": datetime.now(tz=UTC),  # datetime (nested)
                "payload_data_class": "internal",
            },
        ),
    ]
    svc, _session = _build_evaluator(events)
    output = tmp_path / "audit-export.jsonl"

    summary = await svc.export_jsonl(
        tenant_id=_TENANT_ID,
        start=datetime.now(tz=UTC) - timedelta(days=1),
        end=datetime.now(tz=UTC) + timedelta(days=1),
        output_path=output,
    )
    # JSON-roundtrip normalize により UUID/datetime が str に変換され reject されない
    assert summary.rows_exported == 1
    assert summary.rows_rejected_raw_secret == 0
    body = output.read_text(encoding="utf-8").strip()
    row = json.loads(body)
    # payload 内の UUID は str 化されている
    assert row["payload"]["approval_id"] == str(approval_uuid)


def test_audit_export_summary_dataclass() -> None:
    """AuditExportSummary dataclass shape."""

    summary = AuditExportSummary(
        timestamp="2026-05-17T00:00:00+00:00",
        tenant_id=_TENANT_ID,
        rows_exported=10,
        rows_rejected_raw_secret=0,
        output_path="/tmp/x.jsonl",  # noqa: S108 (test only, dataclass shape verify)
        started_at="2026-05-17T00:00:00+00:00",
        completed_at="2026-05-17T00:01:00+00:00",
    )
    assert summary.rows_exported == 10
    assert summary.error_message is None
