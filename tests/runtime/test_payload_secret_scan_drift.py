"""F-002 (R2): drift detection test。

AgentRunEvent / Artifact / ContextSnapshot 全 repository で同 module を使うことを
確認する parity test。共通 module (_payload_secret_scan.py) の存在 + 各 repository
からの import を検証する。
"""

from __future__ import annotations

import pytest


def test_all_repositories_share_same_secret_scanner() -> None:
    from backend.app.repositories import _payload_secret_scan
    from backend.app.repositories import agent_run_event
    from backend.app.repositories import artifact
    from backend.app.repositories import context_snapshot

    assert (
        agent_run_event._PROHIBITED_PAYLOAD_KEYS
        is _payload_secret_scan._PROHIBITED_PAYLOAD_KEYS
    )
    assert artifact._PROHIBITED_PAYLOAD_KEYS is _payload_secret_scan._PROHIBITED_PAYLOAD_KEYS
    assert (
        context_snapshot._PROHIBITED_PAYLOAD_KEYS
        is _payload_secret_scan._PROHIBITED_PAYLOAD_KEYS
    )


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
