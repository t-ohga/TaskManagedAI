"""Observability settings (env-driven).

Sprint 11.5 batch 0 plan v2 §M-2 adopt: dependency pin policy は pyproject.toml で固定.
Sprint 11.5 batch 0 plan v2 §H-1 adopt: `/metrics` endpoint IP allowlist は
`ALLOWED_METRICS_BIND_NETWORKS` で enforce (127.0.0.1 + Tailscale CGNAT 100.64/10).
Sprint 11.5 batch 1 Codex F-PR41-003 P1 adopt: Docker bridge subnet を env 経由で
`additional_metrics_allowed_networks` で extend 可能 (observability profile 起動時).
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
"""`/metrics` endpoint への access を許可する **default** IP 範囲 (immutable).

`ObservabilitySettings.additional_metrics_allowed_networks` で env 経由
extension 可能 (Sprint 11.5 batch 1 Codex F-PR41-003 P1 adopt).
"""


def _parse_additional_networks(value: str) -> frozenset[IPv4Network | IPv6Network]:
    """カンマ区切り CIDR 文字列を network set に変換 (env 入力用)."""

    if not value.strip():
        return frozenset()
    networks: list[IPv4Network | IPv6Network] = []
    for raw in value.split(","):
        stripped = raw.strip()
        if not stripped:
            continue
        networks.append(ip_network(stripped, strict=False))
    return frozenset(networks)


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

    # Codex F-PR41-003 P1 adopt: Docker bridge subnet (172.16.0.0/12 / 192.168.0.0/16)
    # から Prometheus scrape する場合の allowlist 拡張. production VPS の Tailscale 内
    # 運用では空文字列 (default、127.0.0.0/8 + ::1/128 + 100.64.0.0/10 のみ).
    # 例: `TASKMANAGEDAI_ADDITIONAL_METRICS_ALLOWED_NETWORKS="172.16.0.0/12,192.168.0.0/16"`
    additional_metrics_allowed_networks: str = Field(default="")


@lru_cache(maxsize=1)
def get_observability_settings() -> ObservabilitySettings:
    """Return cached `ObservabilitySettings` instance.

    `functools.lru_cache` で env を 1 度だけ評価。test では `cache_clear()` を呼んで
    env override 後の再評価が可能。
    """

    return ObservabilitySettings()


def resolve_metrics_allowed_networks(
    settings: ObservabilitySettings | None = None,
) -> frozenset[IPv4Network | IPv6Network]:
    """`/metrics` allowlist を default + additional (env) で merge.

    Codex F-PR41-003 P1 adopt: observability profile 起動時に Docker bridge subnet
    を env 経由で追加可能 (production VPS 運用では空文字列 default 維持).
    """

    cfg = settings or get_observability_settings()
    additional = _parse_additional_networks(cfg.additional_metrics_allowed_networks)
    return ALLOWED_METRICS_BIND_NETWORKS | additional


__all__ = [
    "ALLOWED_METRICS_BIND_NETWORKS",
    "ObservabilitySettings",
    "get_observability_settings",
    "resolve_metrics_allowed_networks",
]
