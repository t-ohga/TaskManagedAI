"""Sprint 11.5 batch 1 (BL-0133): structured logging (JSON Lines) tests.

Verify items (plan v1 §6.1):
- `setup_logging()` で JsonLinesFormatter attach
- log record が JSON Lines parse 可能
- label injection (`tenant_id` / `actor_id_hash` / `run_id` / `trace_id` / `payload_data_class`)
- raw secret reject (`sk-`, `ghp_`, prohibited key)
- `actor_id` raw → hash prefix 自動変換、raw が JSON output に出ない
- `LOKI_LABEL_FIELDS` set integrity
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Generator

import pytest

from backend.app.observability.config import ObservabilitySettings
from backend.app.observability.logging import (
    LOKI_LABEL_FIELDS,
    JsonLinesFormatter,
    hash_actor_id,
    reset_logging_state,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _reset_logging() -> Generator[None, None, None]:
    """各 test 終了時に logging state を reset."""

    yield
    reset_logging_state()


def _settings(enabled: bool = True) -> ObservabilitySettings:
    return ObservabilitySettings(
        observability_enabled=enabled,
        otel_exporter_otlp_endpoint="",
    )


def _emit_and_capture(record_args: dict[str, object], message: str = "test_event") -> dict[str, object]:
    """LogRecord を JsonLinesFormatter で format し、JSON dict を返す."""

    formatter = JsonLinesFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=None,
        exc_info=None,
    )
    for key, value in record_args.items():
        setattr(record, key, value)
    output = formatter.format(record)
    return json.loads(output)


def test_setup_logging_attaches_json_handler() -> None:
    setup_logging(settings=_settings())
    root = logging.getLogger()
    json_handlers = [h for h in root.handlers if isinstance(h.formatter, JsonLinesFormatter)]
    assert len(json_handlers) >= 1


def test_setup_logging_disabled_is_noop() -> None:
    setup_logging(settings=_settings(enabled=False))
    root = logging.getLogger()
    # disabled の場合 handler attach されない (既存 default のままか empty).
    assert all(not isinstance(h.formatter, JsonLinesFormatter) for h in root.handlers)


def test_setup_logging_idempotent() -> None:
    setup_logging(settings=_settings())
    json_count_after_first = len(
        [h for h in logging.getLogger().handlers if isinstance(h.formatter, JsonLinesFormatter)]
    )
    setup_logging(settings=_settings())
    setup_logging(settings=_settings())
    json_count_after_third = len(
        [h for h in logging.getLogger().handlers if isinstance(h.formatter, JsonLinesFormatter)]
    )
    # idempotent: 3 回 call でも attach 数 ≦ 初回 + 1 (test environment の他 handler 数に依存しない).
    assert json_count_after_third == json_count_after_first


def test_json_format_produces_parseable_output() -> None:
    payload = _emit_and_capture({}, message="hello world")
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "hello world"
    assert "time" in payload


def test_json_format_injects_loki_labels() -> None:
    payload = _emit_and_capture(
        {
            "tenant_id": 42,
            "run_id": "run-abc",
            "trace_id": "trace-xyz",
            "payload_data_class": "internal",
        }
    )
    assert payload["tenant_id"] == 42
    assert payload["run_id"] == "run-abc"
    assert payload["trace_id"] == "trace-xyz"
    assert payload["payload_data_class"] == "internal"


def test_json_format_converts_raw_actor_id_to_hash() -> None:
    """`actor_id` raw が `extra=...` で渡されたら、JSON output には `actor_id_hash`
    の 8-char prefix のみが残り、raw 値は消える.
    """

    raw_actor = "alice@example.com"
    payload = _emit_and_capture({"actor_id": raw_actor})
    assert "actor_id" not in payload
    assert payload["actor_id_hash"] == hash_actor_id(raw_actor)
    assert len(payload["actor_id_hash"]) == 8


def test_json_format_rejects_raw_secret_in_message() -> None:
    formatter = JsonLinesFormatter()
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="leaked sk-fakeButLooksReal0123456789ABCDEF",
        args=None,
        exc_info=None,
    )
    with pytest.raises(ValueError, match="raw secret pattern"):
        formatter.format(record)


def test_json_format_rejects_raw_secret_in_extra() -> None:
    formatter = JsonLinesFormatter()
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ok",
        args=None,
        exc_info=None,
    )
    record.leaked_key = "ghp_FakeBut20PlusCharsABCDEFGHIJ"  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="raw secret pattern"):
        formatter.format(record)


def test_json_format_rejects_prohibited_key() -> None:
    formatter = JsonLinesFormatter()
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ok",
        args=None,
        exc_info=None,
    )
    record.api_key = "anything"  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="prohibited key"):
        formatter.format(record)


def test_loki_label_fields_set_integrity() -> None:
    """Plan v1 §設計判断 line 76 の 5 label のみ promtail で label 化."""

    expected = frozenset(
        {"tenant_id", "actor_id_hash", "run_id", "trace_id", "payload_data_class"}
    )
    assert LOKI_LABEL_FIELDS == expected


def test_hash_actor_id_produces_8_char_hex() -> None:
    result = hash_actor_id("user-1@example.com")
    assert len(result) == 8
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_actor_id_rejects_empty() -> None:
    with pytest.raises(ValueError):
        hash_actor_id("")


def test_setup_logging_attaches_role_filter() -> None:
    """`setup_logging(role="api")` で全 log record に `service_role="api"` が attach."""

    setup_logging(settings=_settings(), role="api")
    root = logging.getLogger()

    # capture log via StringIO via additional handler.
    buf = io.StringIO()
    sniff = logging.StreamHandler(stream=buf)
    sniff.setFormatter(JsonLinesFormatter())
    root.addHandler(sniff)

    test_logger = logging.getLogger("test.role")
    test_logger.info("hello")

    output = buf.getvalue().strip()
    payload = json.loads(output)
    assert payload["service_role"] == "api"
    assert payload["service_name"] == "taskmanagedai"


def test_end_to_end_json_log_via_root() -> None:
    """root logger 経由で log を emit し、JSON Lines として stdout に書き出される."""

    setup_logging(settings=_settings())
    root = logging.getLogger()
    buf = io.StringIO()
    sniff = logging.StreamHandler(stream=buf)
    sniff.setFormatter(JsonLinesFormatter())
    root.addHandler(sniff)

    test_logger = logging.getLogger("test.e2e")
    test_logger.info(
        "structured_event",
        extra={
            "tenant_id": 1,
            "actor_id": "human-1",
            "run_id": "r-1",
            "trace_id": "t-1",
            "payload_data_class": "public",
        },
    )

    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["message"] == "structured_event"
    assert payload["tenant_id"] == 1
    assert payload["actor_id_hash"] == hash_actor_id("human-1")
    assert payload["run_id"] == "r-1"
    assert payload["trace_id"] == "t-1"
    assert payload["payload_data_class"] == "public"
    assert "actor_id" not in payload
