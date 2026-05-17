"""Observability stack foundation (Sprint 11.5 batch 0、BL-0131 + BL-0132).

OTel TracerProvider + Prometheus metrics exporter の public API.

CRITICAL invariant trace:
- deny-by-default: `/metrics` endpoint は 127.0.0.1 bind + IP allowlist middleware の 2 layer 防御
- SecretBroker boundary: span attribute / label は `_payload_secret_scan` 経由で raw secret reject
- Provider Compliance: `payload_data_class` / `allowed_data_class` / `effective_allowed_data_class`
  の 3 別 dimension (合算禁止)、`DATA_CLASS_ORDINAL` import で ordinal 順序強制
- 5+ source enum integrity: `gateway_kind` (tool / runner) は `ai-output-boundary.md §9` source 整合
"""

from __future__ import annotations

from backend.app.observability.config import (
    ALLOWED_METRICS_BIND_NETWORKS,
    ObservabilitySettings,
    get_observability_settings,
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
    create_metrics_router,
    setup_prometheus,
)

__all__ = [
    "ALLOWED_METRICS_BIND_NETWORKS",
    "ObservabilitySettings",
    "PrometheusMetricsAccessGuard",
    "create_metrics_router",
    "get_observability_settings",
    "record_approval_span",
    "record_cost_span",
    "record_runner_span",
    "setup_otel",
    "setup_prometheus",
    "shutdown_otel",
]
