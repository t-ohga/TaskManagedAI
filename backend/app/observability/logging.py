"""Structured (JSON Lines) logging integration for Loki shipping.

Sprint 11.5 batch 1 (BL-0133):
- JSON formatter (`logging.Formatter` subclass) で all log records を JSON Lines に
- label injection: `tenant_id` / `actor_id` (hash 8-char prefix) / `run_id` / `trace_id`
  / `payload_data_class` を log record に attach (`extra=...` 経由)
- raw secret redaction: `assert_no_raw_secret` を emit 前 path で reject (AC-HARD-02 整合)
- `setup_logging()` が root logger に JSON handler を attach、stdout に書き出す
  (Docker promtail が stdout scrape)

CRITICAL invariant trace:
- SecretBroker boundary: log record の message / extra dict は `_payload_secret_scan`
  経由で raw secret reject。Loki shipping 経路には redacted のみ流入.
- cardinality 制御: `actor_id` は raw 不可、8-char hex hash prefix のみ.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from collections.abc import Mapping
from typing import Any, Final, cast

from backend.app.observability.config import (
    ObservabilitySettings,
    get_observability_settings,
)
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

logger = logging.getLogger(__name__)

# Sprint 11.5 batch 1: Loki label として extract される JSON field の固定 set.
# cardinality 制御のため、これら 5 label のみ promtail で label 化 (他は log body).
LOKI_LABEL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "tenant_id",
        "actor_id_hash",  # raw actor_id 不可、8-char hex prefix
        "run_id",
        "trace_id",
        "payload_data_class",
    }
)

# log record の `extra=...` に raw `actor_id` を渡すと自動的に hash prefix に変換.
_RAW_ACTOR_ID_KEY: Final[str] = "actor_id"
_HASHED_ACTOR_ID_KEY: Final[str] = "actor_id_hash"
_ACTOR_ID_HASH_LENGTH: Final[int] = 8

# Pydantic / Python が暗黙に attach する logging field (時刻 / level / module / etc.)
# JSON output に含める標準 field set.
_STANDARD_LOG_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "asctime",
        "message",
        "taskName",
    }
)


def hash_actor_id(actor_id: str) -> str:
    """`actor_id` を sha256 8-char hex prefix に redact (cardinality 制御).

    raw `actor_id` を Loki label として出力すると tenant scale で cardinality
    explosion するため、hash 8-char prefix で固定.
    """

    if not isinstance(actor_id, str) or not actor_id:
        raise ValueError("actor_id must be non-empty str")
    digest = hashlib.sha256(actor_id.encode("utf-8")).hexdigest()
    return digest[:_ACTOR_ID_HASH_LENGTH]


class JsonLinesFormatter(logging.Formatter):
    """Format LogRecord to single-line JSON.

    raw secret pattern が含まれる log は emit 前に `assert_no_raw_secret` 経由 reject.
    `actor_id` が `extra=...` で渡されたら、自動的に `actor_id_hash` に変換 + 削除.
    """

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload: dict[str, Any] = {
            "time": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }

        # extra=... で渡された custom field を抽出.
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_FIELDS:
                continue
            if key.startswith("_"):
                continue
            payload[key] = value

        # raw actor_id を hash prefix に変換 (raw を JSON output に残さない).
        if _RAW_ACTOR_ID_KEY in payload:
            raw = payload.pop(_RAW_ACTOR_ID_KEY)
            if isinstance(raw, str) and raw:
                payload[_HASHED_ACTOR_ID_KEY] = hash_actor_id(raw)

        # exception info を attach.
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # raw secret pattern を message + payload で reject (emit 前 single source).
        # AC-HARD-02 secret_canary_no_leak Hard Gate 整合.
        assert_no_raw_secret(message)
        assert_no_raw_secret(payload)

        return json.dumps(payload, ensure_ascii=False, default=str)


_logging_state: dict[str, object] = {"configured": False, "original_factory": None}


def setup_logging(
    *,
    role: str | None = None,
    settings: ObservabilitySettings | None = None,
    level: int = logging.INFO,
) -> None:
    """Attach JsonLinesFormatter to root logger (stdout, Docker stdout scrape 対応).

    `observability_enabled=False` の場合 NoOp.

    Idempotent: 同 process 内で複数 call されても root logger を 2 重 attach しない.

    `role` / `service_name` injection は `logging.setLogRecordFactory` (process-global)
    経由で全 LogRecord に attach. Propagated log record にも適用される.

    Args:
        role: optional override (api / worker / runner、log record の `service_role` field).
        settings: optional override (test 用).
        level: logging level (default INFO).
    """

    cfg = settings or get_observability_settings()
    if not cfg.observability_enabled:
        return

    if _logging_state.get("configured"):
        return

    service_role = role or cfg.otel_service_role
    service_name = cfg.otel_service_name

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonLinesFormatter())

    root = logging.getLogger()
    # 既存 handler を全 detach (Docker stdout shipping に集約).
    root.handlers = [handler]
    root.setLevel(level)

    # LogRecordFactory override で全 LogRecord (propagated 経路含む) に
    # `service_role` / `service_name` を attach.
    original_factory = logging.getLogRecordFactory()
    _logging_state["original_factory"] = original_factory

    def _record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:  # noqa: ANN401 (LogRecord factory signature requires Any)
        record = original_factory(*args, **kwargs)
        if not hasattr(record, "service_role"):
            record.service_role = service_role
        if not hasattr(record, "service_name"):
            record.service_name = service_name
        return record

    logging.setLogRecordFactory(_record_factory)

    _logging_state["configured"] = True
    logger.info("structured_logging_initialized", extra={"role": service_role})


def reset_logging_state() -> None:
    """test 用: idempotent guard を reset (per-test fixture 経由).

    Production code でも shutdown sequence で call 可能.
    """

    if _logging_state.get("configured"):
        # original factory を restore.
        original = _logging_state.get("original_factory")
        if callable(original):
            logging.setLogRecordFactory(cast(Any, original))
    _logging_state["configured"] = False
    _logging_state["original_factory"] = None
    root = logging.getLogger()
    root.handlers = []
    for f in list(root.filters):
        root.removeFilter(f)


def _validated_label_fields(extra: Mapping[str, object]) -> dict[str, object]:
    """`extra=...` で Loki label として扱う field を抽出 + cardinality / raw secret check.

    `LOKI_LABEL_FIELDS` set のみ抽出、`actor_id` は hash prefix に変換.
    """

    result: dict[str, object] = {}
    for field in LOKI_LABEL_FIELDS:
        if field in extra:
            value = extra[field]
            result[field] = value
    # `actor_id` raw を hash に変換.
    if _RAW_ACTOR_ID_KEY in extra and _HASHED_ACTOR_ID_KEY not in result:
        raw = cast(str, extra[_RAW_ACTOR_ID_KEY])
        if isinstance(raw, str) and raw:
            result[_HASHED_ACTOR_ID_KEY] = hash_actor_id(raw)
    return result


__all__ = [
    "JsonLinesFormatter",
    "LOKI_LABEL_FIELDS",
    "hash_actor_id",
    "reset_logging_state",
    "setup_logging",
]
