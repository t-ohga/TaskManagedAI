"""OpenTelemetry TracerProvider setup + auto-instrument + custom span helpers.

Sprint 11.5 batch 0 (BL-0131).

CRITICAL invariant trace:
- SecretBroker boundary: span attribute は `assert_no_raw_secret` で raw secret reject (single source).
- Provider Compliance 3 dimension: `payload_data_class` / `allowed_data_class` /
  `effective_allowed_data_class` を別 attribute (合算禁止).
- 5+ source enum integrity: `gateway_kind` (tool / runner) は既存 `_GATEWAY_KIND_VALUES` source 整合.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Final, Literal

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# OTel `Attributes` 型 (Mapping[str, AttributeValue]) と整合.
AttributeValue = (
    str
    | bool
    | int
    | float
    | Sequence[str]
    | Sequence[bool]
    | Sequence[int]
    | Sequence[float]
)

from backend.app.domain.artifact.data_class import (
    DATA_CLASS_ORDINAL,
    PayloadDataClass,
)
from backend.app.observability.config import (
    ObservabilitySettings,
    get_observability_settings,
)
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

logger = logging.getLogger(__name__)

GatewayKind = Literal["tool", "runner"]
"""`ai-output-boundary.md §9` enum source: gateway 種別.

`tool_mutating_gateway_stub` (MCP / external tool) は `gateway_kind="tool"`、
`runner_mutation_gateway` (runner sandbox patch) は `gateway_kind="runner"`.
"""

_GATEWAY_KIND_VALUES: Final[frozenset[str]] = frozenset({"tool", "runner"})

_ALLOWED_DATA_CLASS_VALUES: Final[frozenset[str]] = frozenset(DATA_CLASS_ORDINAL.keys())

_provider_state: dict[str, TracerProvider | None] = {"provider": None}


def setup_otel(
    *,
    role: str | None = None,
    settings: ObservabilitySettings | None = None,
) -> TracerProvider | None:
    """Initialize OTel TracerProvider + auto-instrument FastAPI / httpx / SQLAlchemy / Redis.

    `observability_enabled=False` の場合、NoOp を返す.
    `otel_exporter_otlp_endpoint` 空の場合、in-memory tracer のみ (export しない、test default).

    Args:
        role: optional override (api / worker / runner). default は env から resolve.
        settings: optional override (test 用).

    Returns:
        TracerProvider instance、または NoOp 時は None.
    """

    cfg = settings or get_observability_settings()
    if not cfg.observability_enabled:
        logger.info("otel_setup_skipped_disabled")
        return None

    service_role = role or cfg.otel_service_role
    resource = Resource.create(
        {
            "service.name": cfg.otel_service_name,
            "service.namespace": "taskmanagedai",
            "service.role": service_role,
        }
    )
    provider = TracerProvider(resource=resource)

    if cfg.otel_exporter_otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=cfg.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info("otel_setup_with_otlp_exporter", extra={"role": service_role})
    else:
        logger.info("otel_setup_in_memory_only", extra={"role": service_role})

    trace.set_tracer_provider(provider)
    _provider_state["provider"] = provider

    # auto-instrument 5 種 (FastAPI / httpx / SQLAlchemy / Redis / arq).
    # arq は OTLP 公式 instrumentation を持たないため、custom span でカバー
    # (`record_runner_span` を arq task 内で呼ぶ runtime contract).
    # role="api" 時のみ FastAPI instrumentor を有効化。worker role では FastAPI を持たないため skip.
    if service_role == "api":
        FastAPIInstrumentor().instrument(tracer_provider=provider)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    SQLAlchemyInstrumentor().instrument(tracer_provider=provider)
    RedisInstrumentor().instrument(tracer_provider=provider)

    return provider


def shutdown_otel() -> None:
    """Shutdown current TracerProvider (flush pending spans).

    `setup_otel` 後の cleanup. NoOp 時は何もしない.
    """

    provider = _provider_state.get("provider")
    if provider is None:
        return
    provider.shutdown()
    _provider_state["provider"] = None


def _sanitize_attributes(attributes: Mapping[str, AttributeValue]) -> dict[str, AttributeValue]:
    """Span attribute から raw secret pattern を reject.

    `_payload_secret_scan.assert_no_raw_secret` (Sprint 4 で確立、`secret_canary_no_leak`
    AC-HARD-02 Hard Gate と整合) を経由。pattern hit 時は ValueError raise.

    Plan v2 §H-3 adopt: redaction layer は新規定義せず既存 helper を import.
    """

    assert_no_raw_secret(dict(attributes))
    return dict(attributes)


def _validate_payload_data_class(value: object, *, attr_name: str) -> PayloadDataClass:
    if not isinstance(value, str):
        raise ValueError(f"{attr_name} must be str, got {type(value).__name__}")
    if value not in _ALLOWED_DATA_CLASS_VALUES:
        raise ValueError(
            f"{attr_name} must be one of {sorted(_ALLOWED_DATA_CLASS_VALUES)}, got {value!r}"
        )
    return value  # type: ignore[return-value]


def _validate_gateway_kind(value: object) -> GatewayKind:
    if not isinstance(value, str):
        raise ValueError(f"gateway_kind must be str, got {type(value).__name__}")
    if value not in _GATEWAY_KIND_VALUES:
        raise ValueError(
            f"gateway_kind must be one of {sorted(_GATEWAY_KIND_VALUES)}, got {value!r}; "
            "`ai-output-boundary.md §9` enum source と整合必須"
        )
    return value  # type: ignore[return-value]


def record_cost_span(
    *,
    provider: str,
    payload_data_class: str,
    allowed_data_class: str,
    effective_allowed_data_class: str,
    estimated_cost_usd: float,
    tenant_id: int,
    extra_attributes: Mapping[str, AttributeValue] | None = None,
) -> None:
    """Provider call cost を span として emit (BL-0131 custom span helper).

    Provider Compliance §3 invariant trace: `payload_data_class` /
    `allowed_data_class` / `effective_allowed_data_class` 3 別 dimension で記録 (合算禁止).
    """

    _validate_payload_data_class(payload_data_class, attr_name="payload_data_class")
    _validate_payload_data_class(allowed_data_class, attr_name="allowed_data_class")
    _validate_payload_data_class(effective_allowed_data_class, attr_name="effective_allowed_data_class")

    attributes: dict[str, AttributeValue] = {
        "taskmanagedai.provider": provider,
        "taskmanagedai.payload_data_class": payload_data_class,
        "taskmanagedai.allowed_data_class": allowed_data_class,
        "taskmanagedai.effective_allowed_data_class": effective_allowed_data_class,
        "taskmanagedai.estimated_cost_usd": estimated_cost_usd,
        "taskmanagedai.tenant_id": tenant_id,
    }
    if extra_attributes:
        attributes.update(extra_attributes)
    sanitized = _sanitize_attributes(attributes)

    tracer = trace.get_tracer("taskmanagedai.observability.cost")
    with tracer.start_as_current_span("provider.cost", attributes=sanitized):
        pass


def record_approval_span(
    *,
    approval_id: str,
    action_class: str,
    decision: str,
    requester_actor_id: str,
    decider_actor_id: str,
    tenant_id: int,
    extra_attributes: Mapping[str, AttributeValue] | None = None,
) -> None:
    """Approval decision を span として emit (BL-0131 custom span helper).

    `approval.4整合 invariant` trace の foundation. 詳細 binding (artifact_hash /
    policy_version / provider_request_fingerprint) は batch 1+ で event-level 計装.
    """

    attributes: dict[str, AttributeValue] = {
        "taskmanagedai.approval_id": approval_id,
        "taskmanagedai.action_class": action_class,
        "taskmanagedai.decision": decision,
        "taskmanagedai.requester_actor_id": requester_actor_id,
        "taskmanagedai.decider_actor_id": decider_actor_id,
        "taskmanagedai.tenant_id": tenant_id,
    }
    if extra_attributes:
        attributes.update(extra_attributes)
    sanitized = _sanitize_attributes(attributes)

    tracer = trace.get_tracer("taskmanagedai.observability.approval")
    with tracer.start_as_current_span("approval.decision", attributes=sanitized):
        pass


def record_runner_span(
    *,
    run_id: str,
    gateway_kind: str,
    result: str,
    tenant_id: int,
    extra_attributes: Mapping[str, AttributeValue] | None = None,
) -> None:
    """Runner / tool gateway 操作を span として emit (BL-0131 custom span helper).

    `gateway_kind` は `tool` (tool_mutating_gateway_stub) / `runner`
    (runner_mutation_gateway) のみ許可、`ai-output-boundary.md §9` enum source 整合.
    """

    gateway = _validate_gateway_kind(gateway_kind)

    attributes: dict[str, AttributeValue] = {
        "taskmanagedai.run_id": run_id,
        "taskmanagedai.gateway_kind": gateway,
        "taskmanagedai.result": result,
        "taskmanagedai.tenant_id": tenant_id,
    }
    if extra_attributes:
        attributes.update(extra_attributes)
    sanitized = _sanitize_attributes(attributes)

    tracer = trace.get_tracer("taskmanagedai.observability.runner")
    with tracer.start_as_current_span(f"runner.{gateway}", attributes=sanitized):
        pass


__all__ = [
    "GatewayKind",
    "record_approval_span",
    "record_cost_span",
    "record_runner_span",
    "setup_otel",
    "shutdown_otel",
]
