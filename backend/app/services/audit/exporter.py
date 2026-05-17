"""Audit export service (Sprint 11.5 batch 3c、BL-0139 + BL-0156).

audit_events を JSON Lines 形式で export、各 row を `assert_no_raw_secret`
で scan、reject (raw secret 除外 invariant の export-time enforcement).

BL-0156 data_class dimension trace:
- export row に `payload_data_class` / `allowed_data_class` /
  `effective_allowed_data_class` を別 field として記録
- 合算の `data_class` 単一 field は禁止 (Provider Compliance 整合)

CRITICAL invariant trace:
- AC-HARD-02 secret_canary_no_leak: export-time に raw secret pattern reject
- export 失敗時は partial file を残さない (atomic write、tempfile + rename)
- actor binding: admin / cron user 限定、AI / runner trigger 経路なし
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.audit_event import AuditEvent
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

logger = logging.getLogger(__name__)


class AuditExportError(ValueError):
    """Audit export guard violation."""


@dataclass(frozen=True, slots=True)
class AuditExportSummary:
    """Audit export run summary (JSON serializable)."""

    timestamp: str
    tenant_id: int
    rows_exported: int
    rows_rejected_raw_secret: int
    output_path: str
    started_at: str
    completed_at: str
    error_message: str | None = None


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _serialize_uuid(obj: object) -> str:
    """JSON dumps default callable: UUID/datetime を str に変換."""

    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"unsupported type for JSON serialization: {type(obj).__name__}")


def _build_export_row(event: AuditEvent) -> dict[str, Any]:
    """audit_event を export row に変換.

    BL-0156: payload に含まれる `payload_data_class` / `allowed_data_class` /
    `effective_allowed_data_class` を top-level field として **別 dimension で抽出**
    (合算 `data_class` 単一 field 禁止).

    UUID / datetime は assert_no_raw_secret が JSON-serializable 型に厳格なため、
    pre-emptively str() 変換.
    """

    # code-reviewer R1 MEDIUM adopt: payload nested UUID/datetime も
    # JSON-roundtrip で normalize (`assert_no_raw_secret` が UUID/datetime を
    # non-JSON-serializable として誤 reject するのを防ぐ).
    raw_payload = dict(event.event_payload) if event.event_payload else {}
    if raw_payload:
        payload = json.loads(json.dumps(raw_payload, default=_serialize_uuid))
    else:
        payload = raw_payload

    # BL-0156: 3 別 data class dimension を top-level に抽出.
    # UUID / datetime は str に変換 (JSON-serializable + assert_no_raw_secret 整合).
    row: dict[str, Any] = {
        "id": str(event.id) if event.id is not None else None,
        "tenant_id": event.tenant_id,
        "event_type": event.event_type,
        "actor_id": str(event.actor_id) if event.actor_id is not None else None,
        "principal_id": (
            str(event.principal_id) if event.principal_id is not None else None
        ),
        "correlation_id": event.correlation_id,
        "trace_id": event.trace_id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "payload": payload,
    }

    # 3 別 dimension を top-level に persist (Provider Compliance 整合).
    for dim_key in (
        "payload_data_class",
        "allowed_data_class",
        "effective_allowed_data_class",
    ):
        if dim_key in payload:
            row[dim_key] = payload[dim_key]

    return row


class AuditExporter:
    """audit_events JSON Lines exporter.

    使用:
        exporter = AuditExporter(session)
        summary = await exporter.export_jsonl(
            tenant_id=1,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 17),
            output_path=Path("/tmp/audit-export.jsonl"),
        )
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        """fail-closed tenant context guard (rotation.py pattern と整合)."""

        current = await get_tenant_context(self.session)
        if current is None:
            await set_tenant_context(self.session, tenant_id)
            return
        await assert_tenant_context(self.session, tenant_id)

    async def _fetch_events(
        self,
        tenant_id: int,
        *,
        start: datetime,
        end: datetime,
    ) -> Iterable[AuditEvent]:
        """tenant_id + date range で audit_events を select."""

        result = await self.session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.created_at >= start,
                AuditEvent.created_at < end,
            )
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
        return list(result.scalars().all())

    async def export_jsonl(
        self,
        *,
        tenant_id: int,
        start: datetime,
        end: datetime,
        output_path: Path,
    ) -> AuditExportSummary:
        """audit_events を JSON Lines に export.

        各 row を `assert_no_raw_secret` で scan、raw secret pattern hit
        があれば row 単位 reject + reject counter increment (全体 fail せず、
        export 完了後 summary で報告).

        atomic write: tempfile に書き出して完了後 rename、partial file を残さない.
        """

        await self._ensure_tenant_context(tenant_id)
        started_at = _now_utc()
        started_iso = started_at.isoformat()

        events = await self._fetch_events(tenant_id, start=start, end=end)

        # tempfile に書く (output_path と同 directory)、完了後 rename.
        # admin export は 1 日 1 回の cron / SSH 経由起動、blocking I/O 許容.
        output_path = output_path.resolve()  # noqa: ASYNC240
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240

        # Codex F-PR51-001 P2 adopt: staged count + final 化 pattern.
        # `staged_written` は file 書き込み中の count、`rows_exported` は atomic
        # rename 成功後に move (failure 時は 0 のまま、cron false positive 防止).
        staged_written = 0
        rows_exported = 0
        rows_rejected = 0
        error_message: str | None = None

        # tempfile.NamedTemporaryFile(delete=False) でファイル handle 取得
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix=".audit-export-", suffix=".jsonl.tmp", dir=output_dir
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                for event in events:
                    row = _build_export_row(event)
                    # AC-HARD-02 enforcement: export-time に raw secret pattern reject.
                    try:
                        assert_no_raw_secret(row, path="$audit_export_row")
                    except ValueError as exc:
                        rows_rejected += 1
                        logger.warning(
                            "audit_export_row_rejected",
                            extra={
                                "tenant_id": tenant_id,
                                "event_id": str(event.id),
                                "reason": "raw_secret_pattern_hit",
                                "error": str(exc),
                            },
                        )
                        continue
                    f.write(
                        json.dumps(row, ensure_ascii=False, default=_serialize_uuid)
                    )
                    f.write("\n")
                    staged_written += 1
            # atomic rename (admin cron 経路、blocking I/O 許容).
            # Codex F-PR51-001 P2: rename 成功後にのみ staged → rows_exported に move.
            tmp_path.replace(output_path)  # noqa: ASYNC240
            rows_exported = staged_written
        except Exception as exc:  # noqa: BLE001 (export failure は summary で報告)
            error_message = type(exc).__name__
            # partial file cleanup (admin cron、blocking I/O 許容)
            if tmp_path.exists():  # noqa: ASYNC240
                tmp_path.unlink(missing_ok=True)  # noqa: ASYNC240
            # Codex F-PR51-001 P2: failure 時に rows_exported=0 維持 (cron false positive 防止).
            # staged_written は別途 logging に出して debug 用に保持.
            logger.error(
                "audit_export_failed",
                extra={
                    "tenant_id": tenant_id,
                    "error": error_message,
                    "staged_rows_before_failure": staged_written,
                },
            )

        completed_at = _now_utc()
        return AuditExportSummary(
            timestamp=started_iso,
            tenant_id=tenant_id,
            rows_exported=rows_exported,
            rows_rejected_raw_secret=rows_rejected,
            output_path=str(output_path),
            started_at=started_iso,
            completed_at=completed_at.isoformat(),
            error_message=error_message,
        )


__all__ = [
    "AuditExportError",
    "AuditExportSummary",
    "AuditExporter",
]
