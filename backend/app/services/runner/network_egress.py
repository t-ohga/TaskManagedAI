"""Sprint 7 BL-0075: NetworkPolicy + egress allowlist enforcement.

ADR-00008 §network_egress + DD-05: P0 runner sandbox は **inbound 禁止
+ deny-all egress** が default。allowlist mode は ADR Gate Criteria #7
(外部公開) 該当のため Sprint 7 内では実装のみで P0 enable 不可。

P0 design:

- ``NetworkPolicy.mode`` = ``deny_all`` (P0 default) | ``allowlist``
- ``allowlist_hosts`` = frozenset[str]、host+port 形式 (例:
  ``"github.com:443"`` / ``"pypi.org:443"``)
- canonicalization: IDNA encode (Punycode) + lowercase + percent-decode +
  port normalize (e.g., ``https://`` → ``:443``)
- IP literal は ``ipaddress`` module で IPv4 / IPv6 / bracket / zone /
  IPv4-mapped IPv6 を体系的に判定 (Codex R1 F-005 adopt)
- ``NetworkPolicy.allowlist()`` で invalid host / port は ValueError で
  fail-closed reject (Codex R1 F-008 adopt)

DNS rebinding 防御 (Codex R1 F-006 partial defer to Sprint 11):

- 本 Sprint では URL parse 時点での IP literal / loopback / link-local /
  ULA / metadata service deny + Docker network=none 前提で「runtime DNS
  解決の IP pinning」は Sprint 11 sidecar proxy + iptables / nftables で
  本実装する。本 module は **URL canonicalization layer** に限定する旨を
  明示。

Docker integration (Sprint 11):

- ``DockerRunnerAdapter`` で iptables / nftables / firewalld rule を
  egress allowlist と同期。Docker network=none に default で設定し、
  allowlist mode 時のみ sidecar proxy 経由で connect IP pinning 実装。

server-owned-boundary §1:

- ``NetworkPolicy`` は orchestrator が server-resolve、caller-supplied
  経路は signature レベルで pass-through (mode + allowlist_hosts のみ
  受付、caller が任意 IP / hostname を挿入する経路なし)。
"""

from __future__ import annotations

import ipaddress
import re
import urllib.parse
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit


class NetworkEgressMode(StrEnum):
    """Network egress mode.

    Codex SP7 audit F-SP7-010 adopt: 現状は 2-source (enum + pytest EXPECTED)。
    DB CHECK / ORM CheckConstraint / Pydantic / API payload integration は
    Sprint 8 で audit / API 接続時に 5+ source 化する (本 module は internal
    deny reason として閉じているため 2-source で許容)。
    """

    DENY_ALL = "deny_all"
    ALLOWLIST = "allowlist"


class EgressDenyReason(StrEnum):
    """Egress check deny reason."""

    MODE_DENY_ALL = "mode_deny_all"
    HOST_EMPTY = "host_empty"
    HOST_INVALID = "host_invalid"
    HOST_NOT_IN_ALLOWLIST = "host_not_in_allowlist"
    PORT_INVALID = "port_invalid"
    PORT_NOT_IN_ALLOWLIST = "port_not_in_allowlist"
    SCHEME_UNSUPPORTED = "scheme_unsupported"
    IP_LITERAL_DENIED = "ip_literal_denied"
    LINK_LOCAL_DENIED = "link_local_denied"
    LOOPBACK_DENIED = "loopback_denied"
    METADATA_SERVICE_DENIED = "metadata_service_denied"
    PRIVATE_RANGE_DENIED = "private_range_denied"
    RESERVED_RANGE_DENIED = "reserved_range_denied"
    MULTICAST_DENIED = "multicast_denied"


# 全 enum 値 (2-source: enum + pytest、Codex F-SP7-010 adopt で 5+ から訂正)
NETWORK_EGRESS_MODES: Final[frozenset[str]] = frozenset(
    m.value for m in NetworkEgressMode
)
EGRESS_DENY_REASONS: Final[frozenset[str]] = frozenset(
    r.value for r in EgressDenyReason
)

# P0 allowed schemes
_ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})

# Default ports per scheme
_DEFAULT_PORTS: Final[dict[str, int]] = {"http": 80, "https": 443}

# Cloud metadata service IPs (AWS / GCP / Azure / DigitalOcean / Alibaba)
_METADATA_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "169.254.169.254",
        "metadata.google.internal",
        "metadata.azure.com",
        "169.254.170.2",  # ECS task metadata
        "100.100.100.200",  # Alibaba public hosting metadata
    }
)

# Codex PR #1 R1 F-PR1-006 P2 adopt: Loopback hostnames (RFC 6761 + common aliases).
# `_classify_ip` は IP literal にしか効かないため、hostname `localhost` 等を allowlist
# check の前に unconditionally deny し、`NetworkPolicy.allowlist({"localhost"})` でも
# loopback 経由の cloud SSRF / 内部 service exfiltration を防止する。
_LOOPBACK_HOSTNAMES: Final[frozenset[str]] = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
    }
)


@dataclass(frozen=True, slots=True)
class EgressViolation:
    reason: EgressDenyReason
    canonical_host: str
    canonical_port: int | None
    raw_target: str


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    """Per-run network egress policy."""

    mode: NetworkEgressMode = NetworkEgressMode.DENY_ALL
    allowlist_hosts: frozenset[str] = field(default_factory=frozenset)
    allowlist_ports: frozenset[int] = field(
        default_factory=lambda: frozenset({80, 443})
    )

    @classmethod
    def p0_default(cls) -> NetworkPolicy:
        """P0 default: deny all egress."""
        return cls(
            mode=NetworkEgressMode.DENY_ALL,
            allowlist_hosts=frozenset(),
            allowlist_ports=frozenset({80, 443}),
        )

    @classmethod
    def allowlist(
        cls,
        hosts: frozenset[str] | set[str] | tuple[str, ...],
        ports: frozenset[int] | set[int] | tuple[int, ...] = frozenset({80, 443}),
    ) -> NetworkPolicy:
        """Sprint 11+ allowlist mode helper. Codex R1 F-008 adopt: fail-closed.

        Hosts must be canonicalizable (IDNA Punycode lowercase). Ports must be
        in valid range 1..65535. Invalid input raises ValueError.
        """
        canonical_hosts: set[str] = set()
        for raw_host in hosts:
            canonical, err = _canonicalize_host(raw_host)
            if err is not None:
                raise ValueError(
                    f"invalid host in NetworkPolicy.allowlist: {raw_host!r} "
                    f"reason={err.value}"
                )
            canonical_hosts.add(canonical)

        for port in ports:
            if not (1 <= port <= 65535):
                raise ValueError(
                    f"invalid port in NetworkPolicy.allowlist: {port} "
                    f"(must be 1..65535)"
                )

        return cls(
            mode=NetworkEgressMode.ALLOWLIST,
            allowlist_hosts=frozenset(canonical_hosts),
            allowlist_ports=frozenset(ports),
        )


def _canonicalize_host(raw: str) -> tuple[str, EgressDenyReason | None]:
    """Canonicalize host string (IDNA + lowercase). Return (host, error?)."""
    if not raw:
        return "", EgressDenyReason.HOST_EMPTY

    candidate = raw.strip().lower()

    # Percent-decode for URL-encoded host (Codex R1 F-008 adopt)
    if "%" in candidate:
        try:
            candidate = urllib.parse.unquote(candidate)
        except (ValueError, UnicodeDecodeError):
            return candidate, EgressDenyReason.HOST_INVALID

    # IDNA encode (Punycode) for IDN hosts
    if any(ord(c) > 127 for c in candidate):
        try:
            candidate = candidate.encode("idna").decode("ascii")
        except UnicodeError:
            return candidate, EgressDenyReason.HOST_INVALID

    # Validate by RFC 952/1123 hostname pattern + IPv6 bracket
    if not re.match(r"^[a-z0-9.\-\[\]:%]+$", candidate):
        return candidate, EgressDenyReason.HOST_INVALID

    return candidate, None


def canonicalize_egress_target(raw: str) -> tuple[str, int | None, str | None]:
    """Parse and canonicalize ``http(s)://host:port/path`` or ``host:port``.

    Returns ``(host, port, scheme)``. host is lowercase Punycode-encoded.
    """
    raw = raw.strip()
    if "://" in raw:
        try:
            parts = urlsplit(raw)
        except ValueError:
            return raw, None, None
        scheme = parts.scheme.lower() if parts.scheme else None
        host = parts.hostname or ""
        # Codex R1 F-008 adopt: parts.port can raise ValueError for malformed
        try:
            port = parts.port
        except ValueError:
            port = None
        if port is None and scheme in _DEFAULT_PORTS:
            port = _DEFAULT_PORTS[scheme]
        canonical, _ = _canonicalize_host(host)
        return canonical, port, scheme

    # host:port form
    if ":" in raw and not raw.startswith("["):
        host_part, _, port_part = raw.partition(":")
        try:
            port = int(port_part)
        except ValueError:
            canonical, _ = _canonicalize_host(host_part)
            return canonical, None, None
        canonical, _ = _canonicalize_host(host_part)
        return canonical, port, None

    # IPv6 bracketed: [::1]:8080
    if raw.startswith("[") and "]" in raw:
        bracket_end = raw.index("]")
        host_part = raw[: bracket_end + 1]
        rest = raw[bracket_end + 1 :]
        port_v6: int | None = None
        if rest.startswith(":"):
            try:
                port_v6 = int(rest[1:])
            except ValueError:
                port_v6 = None
        canonical, _ = _canonicalize_host(host_part)
        return canonical, port_v6, None

    canonical, _ = _canonicalize_host(raw)
    return canonical, None, None


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Codex R1 F-005 adopt: parse host as IP (bracket-aware, zone-aware).

    urlsplit().hostname strips brackets, so ``http://[fc00::1]/`` returns
    ``fc00::1``. ipaddress.ip_address handles both forms.
    """
    if not host:
        return None
    # Strip brackets if present
    candidate = host
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    # Strip zone identifier (%scope)
    if "%" in candidate:
        candidate = candidate.split("%", 1)[0]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _classify_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> EgressDenyReason | None:
    """Classify IP literal. Return deny reason or None (which means any IP
    literal is denied by IP_LITERAL_DENIED in the caller)."""
    if ip.is_loopback:
        return EgressDenyReason.LOOPBACK_DENIED
    if ip.is_link_local:
        return EgressDenyReason.LINK_LOCAL_DENIED
    if ip.is_multicast:
        return EgressDenyReason.MULTICAST_DENIED
    if ip.is_reserved:
        return EgressDenyReason.RESERVED_RANGE_DENIED
    if ip.is_private:
        # Includes IPv6 ULA fc00::/7 + IPv4 RFC1918 + 169.254 (link-local already covered)
        return EgressDenyReason.PRIVATE_RANGE_DENIED
    return None


def check_egress_allowed(
    raw_target: str,
    policy: NetworkPolicy,
) -> EgressViolation | None:
    """Verify egress target against policy. Return Violation or None (allowed)."""

    host, port, scheme = canonicalize_egress_target(raw_target)

    # Scheme validation first (before host check, because file:// has empty host
    # but the threat is the scheme itself).
    if scheme is not None and scheme not in _ALLOWED_SCHEMES:
        return EgressViolation(
            reason=EgressDenyReason.SCHEME_UNSUPPORTED,
            canonical_host=host,
            canonical_port=port,
            raw_target=raw_target,
        )

    # Empty host check
    if not host:
        return EgressViolation(
            reason=EgressDenyReason.HOST_EMPTY,
            canonical_host=host,
            canonical_port=port,
            raw_target=raw_target,
        )

    # Metadata service hosts denied unconditionally (cloud SSRF)
    if host in _METADATA_HOSTS:
        return EgressViolation(
            reason=EgressDenyReason.METADATA_SERVICE_DENIED,
            canonical_host=host,
            canonical_port=port,
            raw_target=raw_target,
        )

    # Codex PR #1 R1 F-PR1-006 P2 adopt: hostname `localhost` 等を loopback として
    # allowlist check の前に deny する。`NetworkPolicy.allowlist({"localhost"})` でも
    # `_classify_ip` は IP literal にしか効かず hostname `localhost` を通過させ得る。
    # loopback host name を unconditionally deny し、allowlist 側で誤許可されない
    # ようにする (cloud SSRF 防御の一環)。
    if host.lower() in _LOOPBACK_HOSTNAMES:
        return EgressViolation(
            reason=EgressDenyReason.LOOPBACK_DENIED,
            canonical_host=host,
            canonical_port=port,
            raw_target=raw_target,
        )

    # Codex R1 F-005 adopt: IP literal detection via ipaddress.ip_address
    # (handles bracket-stripped IPv6 from urlsplit + zone id).
    ip = _parse_ip(host)
    if ip is not None:
        # Check IPv4-mapped IPv6 (e.g., ::ffff:169.254.169.254)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            mapped_str = str(ip.ipv4_mapped)
            if mapped_str in _METADATA_HOSTS:
                return EgressViolation(
                    reason=EgressDenyReason.METADATA_SERVICE_DENIED,
                    canonical_host=host,
                    canonical_port=port,
                    raw_target=raw_target,
                )
            mapped_ip = ipaddress.IPv4Address(mapped_str)
            mapped_reason = _classify_ip(mapped_ip)
            if mapped_reason is not None:
                return EgressViolation(
                    reason=mapped_reason,
                    canonical_host=host,
                    canonical_port=port,
                    raw_target=raw_target,
                )
        # Specific classification (loopback / link-local / private / etc.)
        specific_reason = _classify_ip(ip)
        if specific_reason is not None:
            return EgressViolation(
                reason=specific_reason,
                canonical_host=host,
                canonical_port=port,
                raw_target=raw_target,
            )
        # Any other IP literal denied (DNS rebinding & SSRF defense - URL layer)
        return EgressViolation(
            reason=EgressDenyReason.IP_LITERAL_DENIED,
            canonical_host=host,
            canonical_port=port,
            raw_target=raw_target,
        )

    # Mode: deny_all → always deny
    if policy.mode == NetworkEgressMode.DENY_ALL:
        return EgressViolation(
            reason=EgressDenyReason.MODE_DENY_ALL,
            canonical_host=host,
            canonical_port=port,
            raw_target=raw_target,
        )

    # Mode: allowlist
    if host not in policy.allowlist_hosts:
        return EgressViolation(
            reason=EgressDenyReason.HOST_NOT_IN_ALLOWLIST,
            canonical_host=host,
            canonical_port=port,
            raw_target=raw_target,
        )

    # Codex R1 F-008 adopt: port range 1..65535 strict
    if port is not None and not (1 <= port <= 65535):
        return EgressViolation(
            reason=EgressDenyReason.PORT_INVALID,
            canonical_host=host,
            canonical_port=port,
            raw_target=raw_target,
        )

    if port is not None and port not in policy.allowlist_ports:
        return EgressViolation(
            reason=EgressDenyReason.PORT_NOT_IN_ALLOWLIST,
            canonical_host=host,
            canonical_port=port,
            raw_target=raw_target,
        )

    if port is None and scheme is None:
        # host:port なし & scheme なし → port unspecified、conservatively deny
        return EgressViolation(
            reason=EgressDenyReason.PORT_INVALID,
            canonical_host=host,
            canonical_port=port,
            raw_target=raw_target,
        )

    return None


__all__ = [
    "EGRESS_DENY_REASONS",
    "NETWORK_EGRESS_MODES",
    "EgressDenyReason",
    "EgressViolation",
    "NetworkEgressMode",
    "NetworkPolicy",
    "canonicalize_egress_target",
    "check_egress_allowed",
]
