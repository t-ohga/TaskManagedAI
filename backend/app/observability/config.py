"""Observability settings (env-driven).

Sprint 11.5 batch 0 plan v2 §M-2 adopt: dependency pin policy は pyproject.toml で固定.
Sprint 11.5 batch 0 plan v2 §H-1 adopt: `/metrics` endpoint IP allowlist は
`ALLOWED_METRICS_BIND_NETWORKS` で enforce (127.0.0.1 + Tailscale CGNAT 100.64/10).
"""

from __future__ import annotations

from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_network
from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Tailscale CGNAT range (RFC 6598、100.64.0.0/10) + IPv4/IPv6 loopback.
# `.claude/rules/core.md §6 deny-by-default` + DD-05 § Network boundary.
_DEFAULT_ALLOWED_NETWORK_STRINGS: Final[tuple[str, ...]] = (
    "127.0.0.0/8",
    "::1/128",
    "100.64.0.0/10",
)


def _build_allowed_networks() -> frozenset[IPv4Network | IPv6Network]:
    return frozenset(ip_network(value, strict=False) for value in _DEFAULT_ALLOWED_NETWORK_STRINGS)


ALLOWED_METRICS_BIND_NETWORKS: Final[frozenset[IPv4Network | IPv6Network]] = (
    _build_allowed_networks()
)
"""`/metrics` endpoint への access を許可する IP 範囲 (immutable).

production 環境で 0.0.0.0 bind が誤って導入されても、middleware で本 set 以外を
403 でブロックする (Sprint 11.5 batch 0 plan v2 §H-1)。
"""


class ObservabilitySettings(BaseSettings):
    """OTel + Prometheus observability stack の env-driven settings.

    `TASKMANAGEDAI_OBSERVABILITY_ENABLED` env var で全体 toggle (default: True).
    enabled=False の場合、`setup_otel` / `setup_prometheus` は NoOp.

    `TASKMANAGEDAI_OTEL_EXPORTER_OTLP_ENDPOINT` 空文字列の場合、tracer は in-memory のみ
    (export しない、test 環境 default).
    """

    model_config = SettingsConfigDict(
        env_prefix="TASKMANAGEDAI_",
        case_sensitive=False,
        extra="ignore",
    )

    observability_enabled: bool = Field(default=True)
    prometheus_metrics_enabled: bool = Field(default=True)
    otel_exporter_otlp_endpoint: str = Field(default="")
    otel_service_name: str = Field(default="taskmanagedai")
    otel_service_role: str = Field(default="api", pattern=r"^(api|worker|runner)$")


@lru_cache(maxsize=1)
def get_observability_settings() -> ObservabilitySettings:
    """Return cached `ObservabilitySettings` instance.

    `functools.lru_cache` で env を 1 度だけ評価。test では `cache_clear()` を呼んで
    env override 後の再評価が可能。
    """

    return ObservabilitySettings()


__all__ = [
    "ALLOWED_METRICS_BIND_NETWORKS",
    "ObservabilitySettings",
    "get_observability_settings",
]
