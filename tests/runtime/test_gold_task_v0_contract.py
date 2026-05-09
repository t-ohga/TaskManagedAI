from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

import pytest

from backend.app.domain.provider.adapter import ProviderAdapter
from backend.app.services.providers.anthropic_messages import AnthropicMessagesAdapter
from backend.app.services.providers.gemini import GeminiAdapter
from backend.app.services.providers.mock import MockProviderAdapter
from backend.app.services.providers.openai_responses import OpenAIResponsesAdapter
from eval.provider.gold_task_v0.dataset import DATASET_VERSION_ID, GOLD_TASK_V0_CASES, GoldTaskCase
from eval.provider.gold_task_v0.runner import run_gold_task_against_adapter

_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")


class _Response:
    def __init__(self, status_code: int = 200, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict[str, Any]:
        return self._payload


class _HTTPClient:
    def __init__(self) -> None:
        self.response = _Response()
        self.calls: list[dict[str, Any]] = []

    def set_response(self, status_code: int, payload: dict[str, Any]) -> None:
        self.response = _Response(status_code, payload)

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any],
        timeout: float,
    ) -> _Response:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "json": dict(json),
                "timeout": timeout,
            }
        )
        return self.response


def _resolver(token: str) -> str:
    assert token.startswith("cap-token-")
    return "broker-resolved-provider-credential"


def _adapter_and_http_response(
    provider: str,
    case: GoldTaskCase,
) -> tuple[ProviderAdapter, dict[str, Any] | None]:
    if provider == "mock":
        return MockProviderAdapter(), None

    client = _HTTPClient()
    if provider == "openai":
        return OpenAIResponsesAdapter(client, _resolver), _openai_response(case)
    if provider == "anthropic":
        return AnthropicMessagesAdapter(client, _resolver), _anthropic_response(case)
    if provider == "gemini":
        return GeminiAdapter(client, _resolver), _gemini_response(case)

    raise AssertionError(f"unknown provider {provider!r}")


def _structured_output_for(case: GoldTaskCase) -> dict[str, Any]:
    if case.case_id == "simple_request":
        return {"answer": "Gold Task v0 simple answer"}
    if case.case_id == "structured_output":
        return {
            "summary": "Gold Task v0 structured summary",
            "risk_score": 0.2,
            "next_actions": [{"title": "Review deterministic contract", "priority": "medium"}],
        }
    raise AssertionError(f"case {case.case_id!r} has no structured output")


def _openai_response(case: GoldTaskCase) -> dict[str, Any]:
    if case.expected_status == "safety_refusal":
        return {
            "status_code": 200,
            "payload": {
                "id": f"resp-{case.case_id}",
                "status": "completed",
                "model": "gpt-5.5",
                "finish_reason": "content_filter",
                "output": [{"type": "refusal", "content": []}],
                "usage": {"input_tokens": 17, "output_tokens": 3, "cost_usd": 0.01},
            },
        }

    return {
        "status_code": 200,
        "payload": {
            "id": f"resp-{case.case_id}",
            "status": "completed",
            "model": "gpt-5.5",
            "output_text": json.dumps(_structured_output_for(case)),
            "usage": {"input_tokens": 17, "output_tokens": 5, "cost_usd": 0.01},
        },
    }


def _anthropic_response(case: GoldTaskCase) -> dict[str, Any]:
    if case.expected_status == "safety_refusal":
        return {
            "status_code": 200,
            "payload": {
                "id": f"msg-{case.case_id}",
                "model": "claude-opus-4-7",
                "stop_reason": "content_filter",
                "content": [{"type": "safety_refusal", "text": "redacted refusal"}],
                "usage": {"input_tokens": 13, "output_tokens": 3, "cost_usd": 0.01},
            },
        }

    return {
        "status_code": 200,
        "payload": {
            "id": f"msg-{case.case_id}",
            "model": "claude-opus-4-7",
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"toolu-{case.case_id}",
                    "name": "taskmanagedai_structured_output",
                    "input": _structured_output_for(case),
                }
            ],
            "usage": {"input_tokens": 13, "output_tokens": 6, "cost_usd": 0.01},
        },
    }


def _gemini_response(case: GoldTaskCase) -> dict[str, Any]:
    if case.expected_status == "safety_refusal":
        return {
            "status_code": 200,
            "payload": {
                "modelVersion": "gemini-2.5",
                "candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}],
                "usageMetadata": {
                    "promptTokenCount": 11,
                    "candidatesTokenCount": 2,
                    "cost_usd": 0.01,
                },
            },
        }

    return {
        "status_code": 200,
        "payload": {
            "modelVersion": "gemini-2.5",
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": json.dumps(_structured_output_for(case))}]},
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 11,
                "candidatesTokenCount": 4,
                "cost_usd": 0.01,
            },
        },
    }


@pytest.mark.parametrize("case", GOLD_TASK_V0_CASES, ids=lambda case: case.case_id)
@pytest.mark.parametrize("provider", ["mock", "openai", "anthropic", "gemini"])
def test_gold_task_v0_contract_for_all_provider_adapters(
    provider: str,
    case: GoldTaskCase,
) -> None:
    adapter, http_response = _adapter_and_http_response(provider, case)

    result, validation = run_gold_task_against_adapter(
        adapter,
        case,
        http_mock_response=http_response,
    )

    assert validation.passed is True
    assert validation.failed is False
    assert validation.mismatches == ()
    assert validation.dataset_version_id == DATASET_VERSION_ID
    assert validation.case_id == case.case_id
    assert validation.provider == adapter.provider_name()
    assert validation.api_or_feature == adapter.api_or_feature()
    assert result.status == case.expected_status
    assert _SHA256_HEX_RE.fullmatch(result.provider_request_fingerprint) is not None
    assert case.request_template["context_snapshot_trace"]["dataset_version_id"] == (
        DATASET_VERSION_ID
    )


def test_gold_task_v0_all_adapters_share_expected_status_contract() -> None:
    for case in GOLD_TASK_V0_CASES:
        statuses: set[str] = set()
        for provider in ("mock", "openai", "anthropic", "gemini"):
            adapter, http_response = _adapter_and_http_response(provider, case)
            result, validation = run_gold_task_against_adapter(
                adapter,
                case,
                http_mock_response=http_response,
            )
            assert validation.passed is True
            statuses.add(result.status)

        assert statuses == {case.expected_status}


def test_gold_task_v0_dataset_version_is_traceable_for_context_snapshot() -> None:
    assert DATASET_VERSION_ID == "gold-task-v0-2026-05-09"
    for case in GOLD_TASK_V0_CASES:
        trace = case.request_template["context_snapshot_trace"]
        assert trace == {
            "dataset_version_id": DATASET_VERSION_ID,
            "fixture_id": case.case_id,
            "snapshot_kind": "input",
        }

