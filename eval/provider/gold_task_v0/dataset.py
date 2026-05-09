from __future__ import annotations

from typing import Any

from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.services.agent_runtime.provider_result_mapping import ProviderResultKind

DATASET_VERSION_ID = "gold-task-v0-2026-05-09"

_SIMPLE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["answer"],
    "properties": {
        "answer": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}

_STRUCTURED_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "risk_score", "next_actions"],
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "risk_score": {"type": "number", "minimum": 0, "maximum": 1},
        "next_actions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["title", "priority"],
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


class GoldTaskCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(..., min_length=1)
    request_template: dict[str, Any]
    expected_status: ProviderResultKind
    expected_artifact_shape: dict[str, Any]
    expected_redacted_summary_shape: dict[str, Any] | None = None

    @field_validator("request_template")
    @classmethod
    def _request_template_must_have_contract_fields(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        required = {
            "messages",
            "structured_output_schema",
            "model_resolved_by_provider",
            "payload_data_class_by_provider",
            "provider_compliance_matrix_version",
            "context_snapshot_trace",
        }
        missing = sorted(required.difference(value))
        if missing:
            raise ValueError(f"request_template missing required keys: {missing}")

        trace = value.get("context_snapshot_trace")
        if not isinstance(trace, dict):
            raise ValueError("request_template.context_snapshot_trace must be an object")
        if trace.get("dataset_version_id") != DATASET_VERSION_ID:
            raise ValueError("context_snapshot_trace.dataset_version_id mismatch")
        return value

    @field_validator("expected_artifact_shape", "expected_redacted_summary_shape")
    @classmethod
    def _expected_shapes_must_be_json_schema(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        try:
            validator_for(value).check_schema(value)
        except SchemaError as exc:
            raise ValueError("expected shape must be a valid JSON Schema") from exc
        return value


def _artifact_shape(output_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        **output_schema,
    }


def _success_redacted_summary_shape(
    output_schema: dict[str, Any],
    required_keys: tuple[str, ...],
) -> dict[str, Any]:
    metadata_branch: dict[str, Any] = {
        "type": "object",
        "required": [
            "provider",
            "api_or_feature",
            "structured_output_schema_hash",
            "structured_output_sha256",
            "structured_output_top_level_keys",
        ],
        "properties": {
            "provider": {"type": "string", "minLength": 1},
            "api_or_feature": {"type": "string", "minLength": 1},
            "structured_output_schema_hash": {
                "type": "string",
                "pattern": "^[a-f0-9]{64}$",
            },
            "structured_output_sha256": {
                "type": "string",
                "pattern": "^[a-f0-9]{64}$",
            },
            "structured_output_top_level_keys": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": True,
        "allOf": [
            {
                "properties": {
                    "structured_output_top_level_keys": {
                        "contains": {"const": key},
                    }
                }
            }
            for key in required_keys
        ],
    }
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "anyOf": [_artifact_shape(output_schema), metadata_branch],
    }


_SAFETY_REFUSAL_RESULT_SHAPE: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "anyOf": [
        {
            "type": "object",
            "required": ["mock_status"],
            "properties": {
                "mock_status": {"const": "safety_refusal"},
            },
            "additionalProperties": True,
        },
        {
            "type": "object",
            "required": ["provider", "api_or_feature", "structured_output_schema_hash"],
            "properties": {
                "provider": {"type": "string", "minLength": 1},
                "api_or_feature": {"type": "string", "minLength": 1},
                "structured_output_schema_hash": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$",
                },
                "finish_reason": {"type": "string"},
                "status": {"type": "string"},
            },
            "additionalProperties": True,
        },
    ],
}


def _base_template(
    *,
    case_id: str,
    messages: list[dict[str, Any]],
    structured_output_schema: dict[str, Any],
) -> dict[str, Any]:
    return {
        "messages": messages,
        "structured_output_schema": structured_output_schema,
        "tenant_id": 1,
        "model_resolved_by_provider": {
            "mock": "mock-model",
            "openai": "gpt-5.5",
            "anthropic": "claude-opus-4-7",
            "gemini": "gemini-2.5",
        },
        "payload_data_class_by_provider": {
            "mock": "internal",
            "openai": "internal",
            "anthropic": "internal",
            "gemini": "public",
        },
        "secret_capability_token_by_provider": {
            "openai": "cap-token-openai-gold-task",
            "anthropic": "cap-token-anthropic-gold-task",
            "gemini": "cap-token-gemini-gold-task",
        },
        "provider_compliance_matrix_version": "v2026.05.09-p0-skeleton",
        "max_tokens": 256,
        "temperature": 0,
        "safety_settings": {
            "mode": "gold_task_v0",
            "dataset_version_id": DATASET_VERSION_ID,
            "case_id": case_id,
        },
        "context_snapshot_trace": {
            "dataset_version_id": DATASET_VERSION_ID,
            "fixture_id": case_id,
            "snapshot_kind": "input",
        },
    }


GOLD_TASK_V0_CASES: tuple[GoldTaskCase, ...] = (
    GoldTaskCase(
        case_id="simple_request",
        request_template=_base_template(
            case_id="simple_request",
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": "Summarize the fixture task in one sentence."},
            ],
            structured_output_schema=_SIMPLE_OUTPUT_SCHEMA,
        ),
        expected_status="success",
        expected_artifact_shape=_artifact_shape(_SIMPLE_OUTPUT_SCHEMA),
        expected_redacted_summary_shape=_success_redacted_summary_shape(
            _SIMPLE_OUTPUT_SCHEMA,
            ("answer",),
        ),
    ),
    GoldTaskCase(
        case_id="structured_output",
        request_template=_base_template(
            case_id="structured_output",
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {
                    "role": "user",
                    "content": "Return a risk summary and at least one next action.",
                },
            ],
            structured_output_schema=_STRUCTURED_OUTPUT_SCHEMA,
        ),
        expected_status="success",
        expected_artifact_shape=_artifact_shape(_STRUCTURED_OUTPUT_SCHEMA),
        expected_redacted_summary_shape=_success_redacted_summary_shape(
            _STRUCTURED_OUTPUT_SCHEMA,
            ("summary", "risk_score", "next_actions"),
        ),
    ),
    GoldTaskCase(
        case_id="safety_refusal",
        request_template=_base_template(
            case_id="safety_refusal",
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {
                    "role": "user",
                    "content": (
                        "__mock_force_safety_refusal__ This case must exercise the "
                        "provider safety refusal mapping without exposing unsafe content."
                    ),
                },
            ],
            structured_output_schema=_SIMPLE_OUTPUT_SCHEMA,
        ),
        expected_status="safety_refusal",
        expected_artifact_shape=_artifact_shape(_SIMPLE_OUTPUT_SCHEMA),
        expected_redacted_summary_shape=_SAFETY_REFUSAL_RESULT_SHAPE,
    ),
)

__all__ = ["DATASET_VERSION_ID", "GOLD_TASK_V0_CASES", "GoldTaskCase"]

