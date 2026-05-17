"""Observability stack foundation (Sprint 11.5 batch 0 + 1、BL-0131〜0134).

OTel TracerProvider + Prometheus metrics exporter + structured logging (JSON Lines for Loki).

CRITICAL invariant trace:
- deny-by-default: `/metrics` endpoint は 127.0.0.1 bind + IP allowlist middleware の 2 layer 防御
- SecretBroker boundary: span attribute / metric label / log record は `_payload_secret_scan`
  経由で raw secret reject (single source、batch 0 + batch 1 共通)
- Provider Compliance: `payload_data_class` / `allowed_data_class` / `effective_allowed_data_class`
  の 3 別 dimension (合算禁止)、`DATA_CLASS_ORDINAL` import で ordinal 順序強制
- 5+ source enum integrity: `gateway_kind` (tool / runner) は `ai-output-boundary.md §9` source 整合
- structured logging label cardinality: `actor_id` は raw 不可、8-char hex hash prefix のみ
"""

from __future__ import annotations

from backend.app.observability.config import (
    ALLOWED_METRICS_BIND_NETWORKS,
    ObservabilitySettings,
    get_observability_settings,
)
from backend.app.observability.logging import (
    LOKI_LABEL_FIELDS,
    JsonLinesFormatter,
    hash_actor_id,
    reset_logging_state,
    setup_logging,
)
from backend.app.observability.otel import (
    record_approval_span,
    record_cost_span,
    record_runner_span,
    setup_otel,
    shutdown_otel,
)
from backend.app.observability.prometheus import (
    PrometheusMetricsAccessGuard,
    PrometheusRequestDurationMiddleware,
    create_metrics_router,
    setup_prometheus,
)

__all__ = [
    "ALLOWED_METRICS_BIND_NETWORKS",
    "JsonLinesFormatter",
    "LOKI_LABEL_FIELDS",
    "ObservabilitySettings",
    "PrometheusMetricsAccessGuard",
    "PrometheusRequestDurationMiddleware",
    "create_metrics_router",
    "get_observability_settings",
    "hash_actor_id",
    "record_approval_span",
    "record_cost_span",
    "record_runner_span",
    "reset_logging_state",
    "setup_logging",
    "setup_otel",
    "setup_prometheus",
    "shutdown_otel",
]
