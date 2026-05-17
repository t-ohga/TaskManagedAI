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
    """Build a generic conforming structured output for the case's
    ``structured_output_schema``.

    BL-0163 batch 5h expansion: the dataset now has 30 cases sharing
    two underlying schemas (``_SIMPLE_OUTPUT_SCHEMA`` with single
    ``answer`` field, and ``_STRUCTURED_OUTPUT_SCHEMA`` with summary +
    risk_score + next_actions). Detect the schema's top-level
    required-keys signature instead of per-case dispatch, so adding new
    cases does not require modifying this helper.
    """

    schema = case.request_template.get("structured_output_schema")
    if not isinstance(schema, dict):
        raise AssertionError(
            f"case {case.case_id!r} has no structured_output_schema"
        )
    required = tuple(sorted(schema.get("required", [])))
    if required == ("answer",):
        return {"answer": f"Gold Task v0 generic answer for {case.case_id}"}
    if required == ("next_actions", "risk_score", "summary"):
        return {
            "summary": f"Gold Task v0 generic summary for {case.case_id}",
            "risk_score": 0.2,
            "next_actions": [
                {
                    "title": f"Generic next action for {case.case_id}",
                    "priority": "medium",
                }
            ],
        }
    raise AssertionError(
        f"case {case.case_id!r} has unsupported schema signature {required!r}"
    )


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
    # F-PR36-001 P1 adopt: bumped from gold-task-v0-2026-05-09 (3 cases,
    # Sprint 5) to gold-task-v0-2026-05-17 (30 cases, Sprint 11 batch 5h).
    assert DATASET_VERSION_ID == "gold-task-v0-2026-05-17"
    for case in GOLD_TASK_V0_CASES:
        trace = case.request_template["context_snapshot_trace"]
        assert trace == {
            "dataset_version_id": DATASET_VERSION_ID,
            "fixture_id": case.case_id,
            "snapshot_kind": "input",
        }


def test_gold_task_v0_corpus_has_minimum_thirty_cases() -> None:
    """BL-0163 must_ship line 171: private gold task 30-50 件 (30 件で達成可)."""

    assert len(GOLD_TASK_V0_CASES) >= 30, (
        f"BL-0163 requires ≥30 cases; got {len(GOLD_TASK_V0_CASES)}"
    )


def test_gold_task_v0_corpus_case_ids_are_unique() -> None:
    case_ids = [case.case_id for case in GOLD_TASK_V0_CASES]
    assert len(case_ids) == len(set(case_ids)), (
        f"duplicate case_ids found: {[c for c in case_ids if case_ids.count(c) > 1]}"
    )


def test_gold_task_v0_expansion_cases_carry_metadata() -> None:
    """F-PR36-003 P2 adopt: BL-0163 batch 5h expansion cases must
    carry GoldTaskMetadata (source / domain / payload_data_class /
    sanitization_status). Sprint 5 originals are exempt (3 cases) for
    backwards compatibility.
    """

    sprint5_originals = {"simple_request", "structured_output", "safety_refusal"}
    for case in GOLD_TASK_V0_CASES:
        if case.case_id in sprint5_originals:
            continue
        assert case.task_metadata is not None, (
            f"case {case.case_id!r} from BL-0163 expansion missing task_metadata"
        )
        assert case.task_metadata.domain, (
            f"case {case.case_id!r} task_metadata.domain is empty"
        )
        assert case.task_metadata.payload_data_class in {
            "public",
            "internal",
            "confidential",
            "pii",
        }
        assert case.task_metadata.sanitization_status in {
            "clean",
            "redacted",
            "synthetic",
        }


def test_gold_task_v0_expansion_cases_have_oracle_keywords() -> None:
    """F-PR36-002 P2 adopt: BL-0163 batch 5h expansion cases must
    declare at least one oracle keyword for downstream SP-012
    real-provider verification. Sprint 5 originals exempt.
    """

    sprint5_originals = {"simple_request", "structured_output", "safety_refusal"}
    for case in GOLD_TASK_V0_CASES:
        if case.case_id in sprint5_originals:
            continue
        assert case.task_oracle_keywords, (
            f"case {case.case_id!r} from BL-0163 expansion missing "
            "task_oracle_keywords"
        )

