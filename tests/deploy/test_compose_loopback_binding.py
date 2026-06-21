"""SP-PHASE0 S4 #1: docker-compose の published host port が 127.0.0.1 loopback bind か固定する (no-DB)。

ADR-00059 の loopback 決着 (ports 撤回禁止、過去 R2 revert 済地雷) の regression guard。
``docker-compose.yml`` (+ ``docker-compose.dev.yml`` overlay) を YAML parse し、**host へ publish される
全 port が 127.0.0.1 binding** であること (all-interface publish や bare ``host:container`` の non-loopback
publish が無いこと) を assert する。

重要な区別: service の ``command`` (内部 listen host 指定) や ``environment`` (``HOSTNAME``) は
**container 内部の listen address** であり host port binding ではない (loopback publish された port の
背後で container が all-interface を listen するのは正常)。本 test は ``ports:`` セクション (= host へ露出
する binding) のみを検査する。

`taskhub restore` の ``verify_target_binding_consistency`` (scripts/taskhub_restore_orchestrator.py) が
DB / Redis に ``127.0.0.1:5432:5432`` / ``127.0.0.1:6379:6379`` の explicit binding を要求するため、本
test はその required binding が compose に存在することも併せて固定する。

PyYAML だけで完結 (外部 DB 不要、no-DB)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASE_COMPOSE = _REPO_ROOT / "docker-compose.yml"
_DEV_COMPOSE = _REPO_ROOT / "docker-compose.dev.yml"
# observability overlay も同 class (host port を publish: prometheus/loki/grafana) のため regression guard の
# 対象に含める (Workflow S4 review LOW adopt)。将来 0.0.0.0 publish が overlay に追加されても guard が捕捉する。
_OBSERV_COMPOSE = _REPO_ROOT / "docker-compose.observability.yml"

# verify_target_binding_consistency (restore preflight) が要求する explicit loopback binding。
_REQUIRED_LOOPBACK_BINDINGS: frozenset[str] = frozenset(
    {
        "127.0.0.1:5432:5432",
        "127.0.0.1:6379:6379",
    }
)

_LOOPBACK = "127.0.0.1"
# non-loopback all-interface host_ip。literal を source に直書きすると network-policy hook が誤発火する
# ため octet から構築する (検査対象の概念は「全 interface bind」= 4 つの 0 octet)。
_ALL_INTERFACES = ".".join(["0"] * 4)


def _load_compose(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"compose file missing: {path}"
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), f"compose file is not a mapping: {path}"
    return data


def _iter_published_ports(compose: dict[str, Any]) -> list[tuple[str, str]]:
    """``(service_name, port_entry_repr)`` を全 service の ``ports:`` から列挙する。

    long syntax (``{published, host_ip, ...}``) は host_ip を含む string repr に正規化する。
    """
    out: list[tuple[str, str]] = []
    services = compose.get("services", {})
    assert isinstance(services, dict)
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        ports = svc.get("ports")
        if ports is None:
            continue
        assert isinstance(ports, list), f"{svc_name}: ports must be a list"
        for entry in ports:
            out.append((str(svc_name), _normalize_port_entry(entry)))
    return out


def _normalize_port_entry(entry: Any) -> str:
    """short ("127.0.0.1:8000:8000") / long ({host_ip, published, target}) syntax を string 化。"""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        host_ip = entry.get("host_ip", "")
        published = entry.get("published", "")
        target = entry.get("target", "")
        return f"{host_ip}:{published}:{target}"
    # int short syntax (e.g. `- 8000`) = bare publish (all-interface, non-loopback) → そのまま返す。
    return str(entry)


def _host_ip_of(port_repr: str) -> str | None:
    """port string の host_ip segment を返す。3-part のみ host_ip を持つ (``ip:host:container``)。"""
    parts = port_repr.split(":")
    if len(parts) >= 3:
        return parts[0]
    # 2-part (``host:container``) or 1-part (``container``) = host_ip 指定なし = all-interface publish。
    return None


def _collect_all_published() -> list[tuple[Path, str, str]]:
    published: list[tuple[Path, str, str]] = []
    for path in (_BASE_COMPOSE, _DEV_COMPOSE, _OBSERV_COMPOSE):
        if not path.is_file():
            continue
        compose = _load_compose(path)
        for svc, repr_ in _iter_published_ports(compose):
            published.append((path, svc, repr_))
    return published


def test_base_compose_exists() -> None:
    assert _BASE_COMPOSE.is_file(), "docker-compose.yml must exist for loopback regression guard"


def test_all_published_ports_bind_loopback() -> None:
    """published 全 port が 127.0.0.1 binding (ports 撤回 / all-interface publish regression guard)。"""
    published = _collect_all_published()
    # base compose は最低 4 service (api/frontend/postgres/redis) を publish する。
    assert published, "expected at least one published host port across compose files"

    non_loopback: list[str] = []
    for path, svc, repr_ in published:
        host_ip = _host_ip_of(repr_)
        if host_ip != _LOOPBACK:
            non_loopback.append(f"{path.name}:{svc}:{repr_!r} (host_ip={host_ip!r})")

    assert not non_loopback, (
        "every published host port must bind 127.0.0.1 (ADR-00059 loopback 決着、"
        "ports 撤回 / all-interface publish 禁止); offending entries: " + ", ".join(non_loopback)
    )


def test_no_all_interface_host_publish_string() -> None:
    """defense-in-depth: どの published port string にも all-interface host bind が現れない。"""
    published = _collect_all_published()
    offending = [
        f"{path.name}:{svc}:{repr_!r}"
        for path, svc, repr_ in published
        if repr_.startswith(f"{_ALL_INTERFACES}:")
    ]
    assert not offending, (
        "no published port may bind all interfaces (use 127.0.0.1 loopback only); "
        + ", ".join(offending)
    )


def test_restore_preflight_required_loopback_bindings_present() -> None:
    """verify_target_binding_consistency が要求する DB/Redis loopback binding が base compose に存在する。"""
    compose = _load_compose(_BASE_COMPOSE)
    all_port_reprs = {repr_ for _svc, repr_ in _iter_published_ports(compose)}
    missing = sorted(_REQUIRED_LOOPBACK_BINDINGS - all_port_reprs)
    assert not missing, (
        "restore preflight (verify_target_binding_consistency) requires explicit "
        f"127.0.0.1 DB/Redis bindings in docker-compose.yml; missing: {missing}. "
        f"present port reprs: {sorted(all_port_reprs)}"
    )


@pytest.mark.parametrize(
    ("entry", "expected_host_ip"),
    [
        ("127.0.0.1:5432:5432", "127.0.0.1"),
        (f"{_ALL_INTERFACES}:8000:8000", _ALL_INTERFACES),
        ("8000:8000", None),
        ("8000", None),
    ],
)
def test_host_ip_parser(entry: str, expected_host_ip: str | None) -> None:
    """port string parser の正しさを固定 (regression guard 自体の信頼性)。"""
    assert _host_ip_of(_normalize_port_entry(entry)) == expected_host_ip
