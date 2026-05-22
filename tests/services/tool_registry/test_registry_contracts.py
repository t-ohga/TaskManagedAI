from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from backend.app.domain.policy.action_class import ALL_ACTION_CLASSES, ActionClass
from backend.app.domain.tool_registry.enums import (
    ALL_TOOL_ALLOWED_ACTIONS,
    P0_DENY_TOOL_ACTIONS,
    ToolAllowedAction,
)
from backend.app.services.tool_registry.loader import load_tool_registry

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_PATH = _REPO_ROOT / "config/tool_registry.toml"


def test_tool_allowed_actions_are_not_policy_action_classes() -> None:
    """Read/search tool actions must not be promoted into policy action_class."""

    assert set(get_args(ActionClass)) == set(ALL_ACTION_CLASSES)
    assert set(get_args(ToolAllowedAction)) == set(ALL_TOOL_ALLOWED_ACTIONS)
    assert ALL_TOOL_ALLOWED_ACTIONS.isdisjoint(ALL_ACTION_CLASSES)


def test_registry_config_contains_no_p0_mutating_tool_actions() -> None:
    registry = load_tool_registry(_REGISTRY_PATH)

    configured_actions = {
        action for entry in registry.values() for action in entry.allowed_actions
    }

    assert configured_actions == ALL_TOOL_ALLOWED_ACTIONS
    assert configured_actions.isdisjoint(P0_DENY_TOOL_ACTIONS)


def test_registry_rejects_tool_entry_without_payload_data_class(tmp_path: Path) -> None:
    path = tmp_path / "tool_registry.toml"
    path.write_text(
        """
[meta]
version = "missing-payload-class"
last_updated_at = "2026-05-22"
description = "missing payload data class test"

[[tools]]
tool_key = "missing_payload_class"
transport = "local"
auth_mode = "none"
network_access = "none"
allowed_actions = ["web_fetch"]
trust_tier = "official"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="max_outgoing_data_class"):
        load_tool_registry(path)


def test_registry_rejects_duplicate_allowed_actions(tmp_path: Path) -> None:
    path = tmp_path / "tool_registry.toml"
    path.write_text(
        """
[meta]
version = "duplicate-action"
last_updated_at = "2026-05-22"
description = "duplicate allowed action test"

[[tools]]
tool_key = "duplicate_action"
transport = "local"
auth_mode = "none"
network_access = "none"
allowed_actions = ["web_fetch", "web_fetch"]
trust_tier = "official"
max_outgoing_data_class = "public"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="allowed_actions must not contain duplicates"):
        load_tool_registry(path)
