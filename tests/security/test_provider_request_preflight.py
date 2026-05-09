from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from backend.app.domain.provider.request import ProviderMessage, ProviderRequest
from backend.app.services.providers.preflight import provider_request_preflight

RUN_ID = UUID("00000000-0000-4000-8000-000000005801")

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

_EXPECTED_RAW_SECRET_PATTERN_KINDS = frozenset(
    {
        "openai_api_key",
        "anthropic_api_key",
        "github_installation_token",
        "github_oauth_token",
        "github_personal_token",
        "tailscale_auth_key",
        "age_private_key",
        "pem_private_key",
    }
)


def _unsafe_request(
    *,
    messages: list[Any] | None = None,
    structured_output_schema: dict[str, Any] | None = None,
    safety_settings: dict[str, Any] | None = None,
) -> ProviderRequest:
    resolved_messages = messages
    if resolved_messages is None:
        resolved_messages = [ProviderMessage.model_construct(role="user", content="hello")]

    return ProviderRequest.model_construct(
        tenant_id=1,
        run_id=RUN_ID,
        provider="mock",
        api_or_feature="mock",
        model_resolved="mock-model",
        messages=resolved_messages,
        structured_output_schema=structured_output_schema
        or {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
        },
        payload_data_class="internal",
        provider_compliance_matrix_version="pcm-v1",
        max_tokens=256,
        temperature=0,
        safety_settings=safety_settings,
        secret_capability_token=None,
    )


def _clean_request() -> ProviderRequest:
    return ProviderRequest.model_validate(
        {
            "tenant_id": 1,
            "run_id": RUN_ID,
            "provider": "mock",
            "api_or_feature": "mock",
            "model_resolved": "mock-model",
            "messages": [{"role": "user", "content": "hello"}],
            "structured_output_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
            },
            "payload_data_class": "internal",
            "provider_compliance_matrix_version": "pcm-v1",
            "safety_settings": {"mode": "safe"},
        }
    )


def test_preflight_uses_canonical_21_keys() -> None:
    from backend.app.repositories._payload_secret_scan import _PROHIBITED_PAYLOAD_KEYS

    assert _PROHIBITED_PAYLOAD_KEYS == _EXPECTED_PROHIBITED_PAYLOAD_KEYS
    assert len(_PROHIBITED_PAYLOAD_KEYS) == 21


def test_preflight_uses_canonical_8_regex_patterns() -> None:
    from backend.app.repositories._payload_secret_scan import _RAW_SECRET_PATTERNS

    actual = {kind for kind, _ in _RAW_SECRET_PATTERNS}

    assert actual == _EXPECTED_RAW_SECRET_PATTERN_KINDS
    assert len(actual) == 8


@pytest.mark.parametrize("prohibited_key", sorted(_EXPECTED_PROHIBITED_PAYLOAD_KEYS))
def test_preflight_denies_21_prohibited_keys_across_request_surfaces(
    prohibited_key: str,
) -> None:
    message_request = _unsafe_request(
        messages=[
            ProviderMessage.model_construct(
                role="user",
                content={prohibited_key: "redacted"},
            )
        ]
    )
    schema_request = _unsafe_request(
        structured_output_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            prohibited_key: "redacted",
        }
    )
    safety_request = _unsafe_request(safety_settings={prohibited_key: "redacted"})

    for provider_request in (message_request, schema_request, safety_request):
        result = provider_request_preflight(provider_request)

        assert result.decision == "deny"
        assert result.pattern_hit_kind == f"prohibited_key:{prohibited_key}"


def _openai_token() -> str:
    return "sk-" + "A" * 28


def _anthropic_token() -> str:
    return "sk-" + "ant-" + "A" * 28


def _github_installation_token() -> str:
    return "ghs_" + "A" * 28


def _github_oauth_token() -> str:
    return "gho_" + "A" * 28


def _github_personal_token() -> str:
    return "ghp_" + "A" * 28


def _tailscale_auth_key() -> str:
    return "tskey-" + "a" * 16 + "-" + "b" * 16


def _age_private_key() -> str:
    return "AGE-" + "SECRET-KEY-1" + "A" * 52


def _pem_private_key_header(prefix: str = "") -> str:
    return "-----BEGIN " + prefix + "PRIVATE KEY-----"


_PATTERN_SAMPLES = {
    "openai_api_key": _openai_token,
    "anthropic_api_key": _anthropic_token,
    "github_installation_token": _github_installation_token,
    "github_oauth_token": _github_oauth_token,
    "github_personal_token": _github_personal_token,
    "tailscale_auth_key": _tailscale_auth_key,
    "age_private_key": _age_private_key,
    "pem_private_key": _pem_private_key_header,
}


@pytest.mark.parametrize("hit_kind", sorted(_EXPECTED_RAW_SECRET_PATTERN_KINDS))
def test_preflight_denies_8_raw_secret_regex_patterns(hit_kind: str) -> None:
    sample_factory = _PATTERN_SAMPLES[hit_kind]
    provider_request = _unsafe_request(
        messages=[
            ProviderMessage.model_construct(
                role="user",
                content=f"redacted sample {sample_factory()}",
            )
        ]
    )

    result = provider_request_preflight(provider_request)

    assert result.decision == "deny"
    assert result.pattern_hit_kind == hit_kind


def test_preflight_denies_generic_and_typed_pem_private_key_headers() -> None:
    generic = provider_request_preflight(
        _unsafe_request(
            messages=[
                ProviderMessage.model_construct(
                    role="user",
                    content=_pem_private_key_header(),
                )
            ]
        )
    )
    typed = provider_request_preflight(
        _unsafe_request(
            messages=[
                ProviderMessage.model_construct(
                    role="user",
                    content=_pem_private_key_header("RSA "),
                )
            ]
        )
    )

    assert generic.decision == "deny"
    assert generic.pattern_hit_kind == "pem_private_key"
    assert typed.decision == "deny"
    assert typed.pattern_hit_kind == "pem_private_key"


def test_preflight_allows_clean_provider_request() -> None:
    result = provider_request_preflight(_clean_request())

    assert result.decision == "allow"
    assert result.pattern_hit_kind is None

