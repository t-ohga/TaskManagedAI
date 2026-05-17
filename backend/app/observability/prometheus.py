"""Prometheus metrics exporter + `/metrics` endpoint + IP allowlist middleware.

Sprint 11.5 batch 0 (BL-0132).

CRITICAL invariant trace:
- deny-by-default: `/metrics` endpoint は (1) 127.0.0.1 bind + (2) IP allowlist middleware
  (`PrometheusMetricsAccessGuard`) の 2 layer 防御 (Sprint 11.5 batch 0 plan v2 §H-1).
- Provider Compliance 3 dimension: `payload_data_class` / `allowed_data_class` /
  `effective_allowed_data_class` を別 label (合算禁止).
- SecretBroker boundary: metric description / label value は `assert_no_raw_secret` 経由.
- cardinality 制御: `actor_id` は raw 不可、8-char hash prefix のみ.
"""

from __future__ import annotations

import hashlib
import logging
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Final

from fastapi import APIRouter, Request
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp

from backend.app.domain.artifact.data_class import DATA_CLASS_ORDINAL
from backend.app.observability.config import (
    ALLOWED_METRICS_BIND_NETWORKS,
    ObservabilitySettings,
    get_observability_settings,
)
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

logger = logging.getLogger(__name__)

_ALLOWED_DATA_CLASS_VALUES: Final[frozenset[str]] = frozenset(DATA_CLASS_ORDINAL.keys())

_ACTOR_ID_HASH_PREFIX_LENGTH: Final[int] = 8


def hash_actor_id(actor_id: str) -> str:
    """`actor_id` を sha256 8-char hex prefix に redact.

    Prometheus label cardinality 制御 (Pack §設計判断 line 76、raw actor_id は label 禁止).
    """

    if not isinstance(actor_id, str) or not actor_id:
        raise ValueError("actor_id must be non-empty str")
    digest = hashlib.sha256(actor_id.encode("utf-8")).hexdigest()
    return digest[:_ACTOR_ID_HASH_PREFIX_LENGTH]


def _validate_data_class(value: str, *, label_name: str) -> str:
    if value not in _ALLOWED_DATA_CLASS_VALUES:
        raise ValueError(
            f"{label_name} must be one of {sorted(_ALLOWED_DATA_CLASS_VALUES)}, got {value!r}"
        )
    return value


class PrometheusRegistry:
    """Custom Prometheus registry + label-validated metric definitions.

    global registry に依存せず、test 並列実行可能.
    """

    def __init__(self) -> None:
        self._registry = CollectorRegistry()
        self._enabled = True

        # `tenant_id` を label として全 metric 強制 (boundary invariant).
        # `actor_id` は raw 不可、8-char hash で labelize.

        self.request_duration_seconds = Histogram(
            "taskmanagedai_request_duration_seconds",
            "HTTP request duration in seconds (FastAPI route handlers).",
            labelnames=("method", "endpoint", "status_code", "tenant_id"),
            registry=self._registry,
        )
        self.agent_run_total = Counter(
            "taskmanagedai_agent_run_total",
            "AgentRun count by terminal status and payload_data_class.",
            labelnames=("status", "payload_data_class", "tenant_id"),
            registry=self._registry,
        )
        self.approval_decision_total = Counter(
            "taskmanagedai_approval_decision_total",
            "Approval decision count by action_class and decision.",
            labelnames=("action_class", "decision", "tenant_id"),
            registry=self._registry,
        )
        self.runner_invocation_total = Counter(
            "taskmanagedai_runner_invocation_total",
            "Runner / tool gateway invocation count by gateway_kind and result.",
            labelnames=("gateway_kind", "result", "tenant_id"),
            registry=self._registry,
        )
        self.provider_call_total = Counter(
            "taskmanagedai_provider_call_total",
            "Provider call count by 3 separate data class dimensions (no aggregation).",
            labelnames=(
                "provider",
                "payload_data_class",
                "allowed_data_class",
                "effective_allowed_data_class",
                "decision",
                "tenant_id",
            ),
            registry=self._registry,
        )

    @property
    def registry(self) -> CollectorRegistry:
        return self._registry

    def record_agent_run(self, *, status: str, payload_data_class: str, tenant_id: int) -> None:
        _validate_data_class(payload_data_class, label_name="payload_data_class")
        if tenant_id is None:
            raise ValueError("tenant_id must not be None (tenant boundary invariant).")
        self.agent_run_total.labels(
            status=status,
            payload_data_class=payload_data_class,
            tenant_id=str(tenant_id),
        ).inc()

    def record_provider_call(
        self,
        *,
        provider: str,
        payload_data_class: str,
        allowed_data_class: str,
        effective_allowed_data_class: str,
        decision: str,
        tenant_id: int,
    ) -> None:
        """Provider call を 3 別 dimension で記録.

        合算 `data_class` 単一 dimension は禁止 (`provider-compliance.md §3` invariant).
        """

        _validate_data_class(payload_data_class, label_name="payload_data_class")
        _validate_data_class(allowed_data_class, label_name="allowed_data_class")
        _validate_data_class(
            effective_allowed_data_class, label_name="effective_allowed_data_class"
        )
        if tenant_id is None:
            raise ValueError("tenant_id must not be None (tenant boundary invariant).")
        self.provider_call_total.labels(
            provider=provider,
            payload_data_class=payload_data_class,
            allowed_data_class=allowed_data_class,
            effective_allowed_data_class=effective_allowed_data_class,
            decision=decision,
            tenant_id=str(tenant_id),
        ).inc()

    def expose(self) -> bytes:
        """`/metrics` endpoint で expose する serialized payload."""

        return generate_latest(self._registry)


_registry_state: dict[str, PrometheusRegistry | None] = {"registry": None}


def setup_prometheus(
    *,
    settings: ObservabilitySettings | None = None,
) -> PrometheusRegistry | None:
    """PrometheusRegistry を初期化.

    `prometheus_metrics_enabled=False` の場合 NoOp.
    """

    cfg = settings or get_observability_settings()
    if not cfg.observability_enabled or not cfg.prometheus_metrics_enabled:
        logger.info("prometheus_setup_skipped_disabled")
        return None

    registry = PrometheusRegistry()
    # Metric description は raw secret pattern に触れない (constant 文字列のみ).
    # 念のため description を assert_no_raw_secret に通して fail-fast.
    for metric in (
        registry.request_duration_seconds,
        registry.agent_run_total,
        registry.approval_decision_total,
        registry.runner_invocation_total,
        registry.provider_call_total,
    ):
        assert_no_raw_secret(metric._documentation)  # noqa: SLF001 (Prometheus public API なし)

    _registry_state["registry"] = registry
    return registry


def get_prometheus_registry() -> PrometheusRegistry | None:
    return _registry_state.get("registry")


def create_metrics_router(registry: PrometheusRegistry) -> APIRouter:
    """`/metrics` endpoint を提供する FastAPI router.

    `PrometheusMetricsAccessGuard` middleware が同 path で IP allowlist を強制.
    """

    router = APIRouter()

    @router.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        return PlainTextResponse(registry.expose(), media_type=CONTENT_TYPE_LATEST)

    return router


class PrometheusMetricsAccessGuard(BaseHTTPMiddleware):
    """`/metrics` endpoint を IP allowlist で防御 (Sprint 11.5 batch 0 plan v2 §H-1).

    127.0.0.0/8 (loopback) + ::1/128 (IPv6 loopback) + 100.64.0.0/10 (Tailscale CGNAT)
    のみ allow. 他は 403 Forbidden.

    `X-Forwarded-For` は **信頼しない** (reverse proxy 前提の trust boundary を持ち込まない).
    """

    def __init__(self, app: ASGIApp, *, path_prefix: str = "/metrics") -> None:
        super().__init__(app)
        self._path_prefix = path_prefix

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not request.url.path.startswith(self._path_prefix):
            return await call_next(request)

        client = request.client
        if client is None:
            logger.warning("metrics_access_denied_no_client_host")
            return PlainTextResponse("forbidden", status_code=403)

        try:
            host = ip_address(client.host)
        except ValueError:
            logger.warning(
                "metrics_access_denied_invalid_host", extra={"raw_host": "redacted"}
            )
            return PlainTextResponse("forbidden", status_code=403)

        if not _is_allowed(host):
            logger.warning("metrics_access_denied_non_allowlist")
            return PlainTextResponse("forbidden", status_code=403)

        return await call_next(request)


def _is_allowed(host: IPv4Address | IPv6Address) -> bool:
    for network in ALLOWED_METRICS_BIND_NETWORKS:
        if host.version != network.version:
            continue
        if host in network:
            return True
    return False


__all__ = [
    "PrometheusMetricsAccessGuard",
    "PrometheusRegistry",
    "create_metrics_router",
    "get_prometheus_registry",
    "hash_actor_id",
    "setup_prometheus",
]
