from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.app.domain.tool_registry.enums import (
    ALL_PAYLOAD_DATA_CLASSES,
    ALL_TOOL_ALLOWED_ACTIONS,
    ALL_TOOL_TRUST_TIERS,
)
from backend.app.services.tool_registry.loader import (
    current_tool_manifest,
    load_tool_registry,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_PATH = _REPO_ROOT / "config/tool_registry.toml"


def test_tool_registry_config_loads_and_produces_manifest_lock() -> None:
    registry = load_tool_registry(_REGISTRY_PATH)

    assert registry.registry_version == "sp0045-v1"
    assert set(registry) == {
        "web_fetch",
        "docs_search",
        "code_grep",
        "filesystem_read",
    }
    assert re.fullmatch(r"[a-f0-9]{64}", registry.allowlist_hash)
    assert registry.tool_manifest.as_json() == current_tool_manifest(_REGISTRY_PATH)


def test_tool_registry_hash_is_order_independent(tmp_path: Path) -> None:
    original = _REGISTRY_PATH.read_text(encoding="utf-8")
    parts = original.split("\n[[tools]]\n")
    reordered = "\n[[tools]]\n".join([parts[0], *reversed(parts[1:])])
    path = tmp_path / "tool_registry.toml"
    path.write_text(reordered, encoding="utf-8")

    assert load_tool_registry(path).allowlist_hash == load_tool_registry(
        _REGISTRY_PATH
    ).allowlist_hash


def test_tool_registry_rejects_duplicate_tool_key(tmp_path: Path) -> None:
    path = tmp_path / "tool_registry.toml"
    path.write_text(
        """
[meta]
version = "duplicate"
last_updated_at = "2026-05-22"
description = "duplicate test"

[[tools]]
tool_key = "web_fetch"
transport = "local"
auth_mode = "none"
network_access = "none"
allowed_actions = ["web_fetch"]
trust_tier = "official"
max_outgoing_data_class = "public"

[[tools]]
tool_key = "web_fetch"
transport = "local"
auth_mode = "none"
network_access = "none"
allowed_actions = ["web_fetch"]
trust_tier = "official"
max_outgoing_data_class = "public"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate tool_registry tool_key"):
        load_tool_registry(path)


def test_tool_registry_rejects_mutating_allowed_action(tmp_path: Path) -> None:
    path = tmp_path / "tool_registry.toml"
    path.write_text(
        """
[meta]
version = "mutating"
last_updated_at = "2026-05-22"
description = "mutating test"

[[tools]]
tool_key = "bad_tool"
transport = "local"
auth_mode = "none"
network_access = "none"
allowed_actions = ["repo_write"]
trust_tier = "official"
max_outgoing_data_class = "public"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="allowed_actions"):
        load_tool_registry(path)


def test_tool_registry_rejects_experimental_sensitive_data_class(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tool_registry.toml"
    path.write_text(
        """
[meta]
version = "experimental"
last_updated_at = "2026-05-22"
description = "experimental test"

[[tools]]
tool_key = "experimental_tool"
transport = "local"
auth_mode = "none"
network_access = "none"
allowed_actions = ["web_fetch"]
trust_tier = "experimental"
max_outgoing_data_class = "internal"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="experimental tools may only use"):
        load_tool_registry(path)


def test_tool_registry_enum_constants_cover_config_and_frontend_source() -> None:
    registry = load_tool_registry(_REGISTRY_PATH)
    configured_actions = {
        action for entry in registry.values() for action in entry.allowed_actions
    }
    frontend_source = (
        _REPO_ROOT / "frontend/lib/domain/tool-registry.ts"
    ).read_text(encoding="utf-8")
    adr_source = (
        _REPO_ROOT / "docs/adr/00027_tool_registry_security_boundary.md"
    ).read_text(encoding="utf-8")

    assert configured_actions == ALL_TOOL_ALLOWED_ACTIONS
    for value in ALL_TOOL_ALLOWED_ACTIONS:
        assert f'"{value}"' in frontend_source
        assert f"`{value}`" in adr_source
    for value in ALL_TOOL_TRUST_TIERS:
        assert f'"{value}"' in frontend_source
        assert f"`{value}`" in adr_source
    for value in ALL_PAYLOAD_DATA_CLASSES:
        assert f'"{value}"' in frontend_source
        assert f"`{value}`" in adr_source
