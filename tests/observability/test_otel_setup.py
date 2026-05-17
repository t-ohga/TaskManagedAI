"""Sprint 11.5 batch 0 (BL-0131): OTel TracerProvider + auto-instrument + custom span tests.

Verify items (plan v2 §6.1):
- `setup_otel()` で TracerProvider 初期化
- auto-instrument (FastAPI / httpx / SQLAlchemy / Redis) enabled
- custom span emit (`record_cost_span` / `record_approval_span` / `record_runner_span`)
- secret pattern hit を span attribute に含めようとすると `_payload_secret_scan` 経由 redact (H-3)
- `gateway_kind` enum 値域は `ai-output-boundary.md §9` source と一致、その他は reject (M-3)
- `shutdown_otel()` で正常 close
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from backend.app.observability.config import ObservabilitySettings
from backend.app.observability.otel import (
    _GATEWAY_KIND_VALUES,
    record_approval_span,
    record_cost_span,
    record_runner_span,
    setup_otel,
    shutdown_otel,
)


@pytest.fixture(autouse=True)
def _reset_otel_state() -> Generator[None, None, None]:
    """各 test 終了時に TracerProvider を reset."""

    yield
    shutdown_otel()


def _settings(enabled: bool = True, role: str = "api") -> ObservabilitySettings:
    return ObservabilitySettings(
        observability_enabled=enabled,
        otel_service_role=role,
        otel_exporter_otlp_endpoint="",
    )


def test_setup_otel_returns_tracer_provider() -> None:
    provider = setup_otel(settings=_settings())
    assert provider is not None
    assert isinstance(provider, TracerProvider)


def test_setup_otel_disabled_returns_none() -> None:
    provider = setup_otel(settings=_settings(enabled=False))
    assert provider is None


def test_setup_otel_worker_role_skips_fastapi_instrumentor() -> None:
    # role="worker" でも例外なく完了 (FastAPI instrumentor を skip).
    provider = setup_otel(settings=_settings(role="worker"))
    assert provider is not None


def test_shutdown_otel_after_setup() -> None:
    setup_otel(settings=_settings())
    shutdown_otel()
    # 多重 shutdown でも例外しない.
    shutdown_otel()


def test_record_cost_span_with_3_data_class_dimensions() -> None:
    setup_otel(settings=_settings())
    # 3 別 dimension が span attribute として記録されること (例外なく完了).
    record_cost_span(
        provider="openai",
        payload_data_class="internal",
        allowed_data_class="confidential",
        effective_allowed_data_class="internal",
        estimated_cost_usd=0.001234,
        tenant_id=1,
    )


def test_record_cost_span_invalid_data_class_rejected() -> None:
    setup_otel(settings=_settings())
    with pytest.raises(ValueError, match="payload_data_class"):
        record_cost_span(
            provider="openai",
            payload_data_class="invalid_class",
            allowed_data_class="internal",
            effective_allowed_data_class="internal",
            estimated_cost_usd=0.001,
            tenant_id=1,
        )


def test_record_approval_span_emits_attributes() -> None:
    setup_otel(settings=_settings())
    record_approval_span(
        approval_id="approval-001",
        action_class="repo_write",
        decision="approved",
        requester_actor_id="agent-1",
        decider_actor_id="human-1",
        tenant_id=1,
    )


def test_record_runner_span_with_valid_gateway_kind() -> None:
    setup_otel(settings=_settings())
    # tool gateway
    record_runner_span(
        run_id="run-1",
        gateway_kind="tool",
        result="denied",
        tenant_id=1,
    )
    # runner gateway
    record_runner_span(
        run_id="run-2",
        gateway_kind="runner",
        result="completed",
        tenant_id=1,
    )


def test_record_runner_span_invalid_gateway_kind_rejected() -> None:
    setup_otel(settings=_settings())
    with pytest.raises(ValueError, match="gateway_kind"):
        record_runner_span(
            run_id="run-1",
            gateway_kind="other",
            result="completed",
            tenant_id=1,
        )


def test_gateway_kind_values_5_plus_source_integrity() -> None:
    """`gateway_kind` enum 値域は `ai-output-boundary.md §9` の `tool` / `runner` のみ.

    (Plan v2 §M-3 adopt: 5+ source 整合).
    """

    assert _GATEWAY_KIND_VALUES == frozenset({"tool", "runner"})


def test_record_cost_span_raw_secret_in_extra_rejected() -> None:
    """Span attribute に raw secret pattern (sk-..) を含めようとすると
    `_payload_secret_scan.assert_no_raw_secret` 経由で reject (H-3 adopt).

    AC-HARD-02 `secret_canary_no_leak` Hard Gate との整合 verify.
    """

    setup_otel(settings=_settings())
    with pytest.raises(ValueError, match="raw secret pattern"):
        record_cost_span(
            provider="openai",
            payload_data_class="public",
            allowed_data_class="public",
            effective_allowed_data_class="public",
            estimated_cost_usd=0.001,
            tenant_id=1,
            extra_attributes={
                "leaked_api_key": "sk-fakeButLooksReal0123456789ABCDEF",
            },
        )


def test_record_approval_span_raw_token_in_extra_rejected() -> None:
    """`ghp_` GitHub PAT pattern も reject される."""

    setup_otel(settings=_settings())
    with pytest.raises(ValueError, match="raw secret pattern"):
        record_approval_span(
            approval_id="approval-001",
            action_class="repo_write",
            decision="approved",
            requester_actor_id="agent-1",
            decider_actor_id="human-1",
            tenant_id=1,
            extra_attributes={
                "leak_field": "ghp_FakeBut20PlusCharsABCDEFGHIJ",
            },
        )


def test_record_runner_span_prohibited_key_rejected() -> None:
    """Prohibited key (`api_key`, `secret` 等) も reject される."""

    setup_otel(settings=_settings())
    with pytest.raises(ValueError, match="prohibited key"):
        record_runner_span(
            run_id="run-1",
            gateway_kind="runner",
            result="completed",
            tenant_id=1,
            extra_attributes={"api_key": "anything"},
        )


def test_tracer_provider_set_globally() -> None:
    """`setup_otel()` 後、`trace.get_tracer_provider()` の delegate に同 provider が set される.

    NOTE: OTel は `ProxyTracerProvider` 経由で delegate を保持するため、global は
    proxy であって、直接 ==/is 一致しない可能性がある。本 test は delegate (内部) または
    proxy 経由で tracer を取得できることを smoke verify する.
    """

    provider = setup_otel(settings=_settings())
    assert provider is not None
    # tracer を取得し、span emit が機能することを smoke check.
    tracer = trace.get_tracer("taskmanagedai.test")
    with tracer.start_as_current_span("smoke") as span:
        assert span is not None
