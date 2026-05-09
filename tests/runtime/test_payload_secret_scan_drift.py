"""F-002 (R2): drift detection test。

AgentRunEvent / Artifact / ContextSnapshot 全 repository で同 module を使うことを
確認する parity test。共通 module (_payload_secret_scan.py) の存在 + 各 repository
からの import を検証する。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENT_RUNS_MIGRATION = _REPO_ROOT / "migrations" / "versions" / "0008_agent_runs_lifecycle.py"

_EXPECTED_PROHIBITED_PAYLOAD_KEYS = frozenset(
    {
        "api_key",
        "api_token",
        "raw_secret",
        "secret",
        "secret_value",
        "private_key",
        "auth_token",
        "bearer_token",
        "capability_token",
        "capability_token_value",
        "provider_key",
        "github_installation_token",
        "github_app_private_key",
        "tailscale_auth_key",
        "sops_age_key",
        "age_private_key",
        "canary_value",
        "raw_canary",
        "secret_capability_token",
        "raw_token",
        "session_token",
    }
)


def _tuple_string_values_from_module(path: Path, constant_name: str) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))

    for node in ast.walk(module):
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != constant_name:
            continue
        if not isinstance(node.value, ast.Tuple):
            raise AssertionError(f"{constant_name} must be a tuple literal.")

        values: set[str] = set()
        for item in node.value.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                raise AssertionError(f"{constant_name} must contain only string literals.")
            values.add(item.value)
        return values

    raise AssertionError(f"{constant_name} was not found in {path}.")


def test_all_repositories_share_same_secret_scanner() -> None:
    from backend.app.repositories import (
        _payload_secret_scan,
        agent_run_event,
        artifact,
        context_snapshot,
    )

    assert (
        agent_run_event._PROHIBITED_PAYLOAD_KEYS
        is _payload_secret_scan._PROHIBITED_PAYLOAD_KEYS
    )
    assert artifact._PROHIBITED_PAYLOAD_KEYS is _payload_secret_scan._PROHIBITED_PAYLOAD_KEYS
    assert (
        context_snapshot._PROHIBITED_PAYLOAD_KEYS
        is _payload_secret_scan._PROHIBITED_PAYLOAD_KEYS
    )


def test_prohibited_payload_key_set_matches_expected_exact_set() -> None:
    from backend.app.repositories._payload_secret_scan import _PROHIBITED_PAYLOAD_KEYS

    assert _PROHIBITED_PAYLOAD_KEYS == _EXPECTED_PROHIBITED_PAYLOAD_KEYS
    assert len(_PROHIBITED_PAYLOAD_KEYS) == 21


def test_agent_run_event_migration_prohibited_keys_match_repository() -> None:
    from backend.app.repositories._payload_secret_scan import _PROHIBITED_PAYLOAD_KEYS

    migration_keys = _tuple_string_values_from_module(
        _AGENT_RUNS_MIGRATION,
        "_PROHIBITED_EVENT_PAYLOAD_KEYS",
    )

    assert migration_keys == _PROHIBITED_PAYLOAD_KEYS
    assert migration_keys == _EXPECTED_PROHIBITED_PAYLOAD_KEYS


def test_anthropic_api_key_pattern_detected() -> None:
    from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

    with pytest.raises(ValueError, match="anthropic_api_key"):
        assert_no_raw_secret({"summary": "key sk-ant-abcdefghijklmnopqrstuv"})


def test_pem_private_key_pattern_detected() -> None:
    from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

    with pytest.raises(ValueError, match="pem_private_key"):
        assert_no_raw_secret(
            {
                "ca": "-----BEGIN RSA PRIVATE KEY-----\n.....",
            }
        )
