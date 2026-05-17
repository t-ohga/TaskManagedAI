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
import re
import time
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Final

from fastapi import APIRouter, Request
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp

from backend.app.domain.artifact.data_class import DATA_CLASS_ORDINAL
from backend.app.observability.config import (
    ObservabilitySettings,
    get_observability_settings,
    resolve_metrics_allowed_networks,
)
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

logger = logging.getLogger(__name__)

_ALLOWED_DATA_CLASS_VALUES: Final[frozenset[str]] = frozenset(DATA_CLASS_ORDINAL.keys())

_ACTOR_ID_HASH_PREFIX_LENGTH: Final[int] = 8

# Sprint 11.5 batch 0 Codex F-PR40-002 P2 adopt: non-enum dynamic label
# (provider / decision / result / status 等) を sanitize する正規表現.
# `[A-Za-z0-9._:/-]{1,128}` のみ allow、それ以外 (raw secret pattern を含む)
# は ValueError reject. cardinality control も兼ねる (128 char 上限).
_SAFE_LABEL_VALUE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")


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


def _sanitize_label_value(value: str, *, label_name: str) -> str:
    """Sprint 11.5 batch 0 Codex F-PR40-002 P2 adopt: non-enum dynamic label を sanitize.

    `provider` (e.g., `openai`/`anthropic`/`gemini`) / `decision` (e.g., `allow`/`deny`/
    `defer`) / `result` (e.g., `completed`/`denied`/`failed`) / `status` (HTTP code 等) は
    upstream payload 由来の動的 string を取りうる。本 helper は **2 layer 防御**:

    1. `_SAFE_LABEL_VALUE_PATTERN` (`[A-Za-z0-9._:/-]{1,128}`) で safe char set
       + 128 char 上限 (cardinality 制御)
    2. `assert_no_raw_secret` で raw secret pattern (`sk-...`, `ghp_...`, `AGE-SECRET-KEY-`
       等の 8 regex pattern + 21 prohibited key) を reject
    """

    if not isinstance(value, str) or not value:
        raise ValueError(f"{label_name} must be non-empty str, got {value!r}")
    if not _SAFE_LABEL_VALUE_PATTERN.fullmatch(value):
        raise ValueError(
            f"{label_name} contains disallowed characters or exceeds 128 chars "
            f"(label_name={label_name!r}); raw secret patterns and high-cardinality "
            "free-form strings are rejected. Pass redacted/enumerated values only."
        )
    # raw secret pattern (sk-/ghp_/AGE-SECRET 等) の最終 check.
    try:
        assert_no_raw_secret(value)
    except ValueError as exc:
        raise ValueError(
            f"{label_name} matches raw secret pattern (label_name={label_name!r}); "
            f"original error redacted"
        ) from exc
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
        _sanitize_label_value(status, label_name="status")
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
        # Codex F-PR40-002 P2 adopt: non-enum dynamic label を sanitize.
        _sanitize_label_value(provider, label_name="provider")
        _sanitize_label_value(decision, label_name="decision")
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


class PrometheusRequestDurationMiddleware(BaseHTTPMiddleware):
    """HTTP request duration を `request_duration_seconds` Histogram に observe.

    Sprint 11.5 batch 0 Codex F-PR40-004 P2 adopt: histogram は定義のみで
    `observe()` 呼出がなければ metric が emit されない。本 middleware が
    method / endpoint / status_code / tenant_id label で request duration を計測.

    `tenant_id` の resolve: request.state に attach されている場合のみ label に使う、
    なければ `"unknown"` (boundary invariant の boot-time/preauth path 対応).
    """

    def __init__(self, app: ASGIApp, *, registry: PrometheusRegistry) -> None:
        super().__init__(app)
        self._registry = registry

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed = time.perf_counter() - start
            status_code = str(response.status_code) if response is not None else "500"
            # endpoint label は route template (e.g., `/api/v1/tickets/{id}`) を優先、
            # それがなければ raw path (high cardinality risk があるが、raw path も
            # `_sanitize_label_value` で 128 char 上限 + safe character set で制約).
            raw_endpoint = (
                request.scope.get("route").path  # type: ignore[union-attr]
                if request.scope.get("route") is not None
                else request.url.path
            )
            try:
                endpoint = _sanitize_label_value(raw_endpoint, label_name="endpoint")
            except ValueError:
                endpoint = "unsanitized"
            tenant_id = getattr(request.state, "tenant_id", None)
            tenant_label = str(tenant_id) if tenant_id is not None else "unknown"

            try:
                self._registry.request_duration_seconds.labels(
                    method=request.method,
                    endpoint=endpoint,
                    status_code=status_code,
                    tenant_id=tenant_label,
                ).observe(elapsed)
            except Exception as exc:  # noqa: BLE001 (telemetry must not break request flow)
                logger.warning("prometheus_observe_failed", extra={"error": str(exc)})


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
    # Codex F-PR41-003 P1 adopt: default allowlist + env additional networks を merge.
    # observability profile 起動時に Docker bridge subnet を追加可能.
    networks = resolve_metrics_allowed_networks()
    for network in networks:
        if host.version != network.version:
            continue
        if host in network:
            return True
    return False


__all__ = [
    "PrometheusMetricsAccessGuard",
    "PrometheusRegistry",
    "PrometheusRequestDurationMiddleware",
    "create_metrics_router",
    "get_prometheus_registry",
    "hash_actor_id",
    "setup_prometheus",
]
