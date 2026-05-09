from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.domain.artifact.data_class import PayloadDataClass
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

ProviderMessageRole = Literal["system", "user", "assistant", "tool"]


class ProviderMessageContentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["text", "image_ref", "tool_result", "tool_use"]
    text: str | None = None
    image_ref: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    output: str | None = None

    @model_validator(mode="after")
    def _fields_must_match_type(self) -> ProviderMessageContentBlock:
        if self.type == "text":
            _require_only_block_fields(self, required=("text",), allowed=("text",))
            return self

        if self.type == "image_ref":
            _require_only_block_fields(
                self,
                required=("image_ref",),
                allowed=("image_ref",),
            )
            return self

        if self.type == "tool_result":
            _require_only_block_fields(
                self,
                required=("tool_call_id", "output"),
                allowed=("tool_call_id", "output"),
            )
            return self

        _require_only_block_fields(
            self,
            required=("tool_call_id", "tool_name"),
            allowed=("tool_call_id", "tool_name"),
        )
        return self


def _require_only_block_fields(
    block: ProviderMessageContentBlock,
    *,
    required: tuple[str, ...],
    allowed: tuple[str, ...],
) -> None:
    all_value_fields = ("text", "image_ref", "tool_call_id", "tool_name", "output")
    missing = [field_name for field_name in required if getattr(block, field_name) is None]
    if missing:
        raise ValueError(
            f"content block type={block.type!r} requires fields: {', '.join(missing)}"
        )

    forbidden = [
        field_name
        for field_name in all_value_fields
        if field_name not in allowed and getattr(block, field_name) is not None
    ]
    if forbidden:
        raise ValueError(
            f"content block type={block.type!r} forbids fields: {', '.join(forbidden)}"
        )


class ProviderMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: ProviderMessageRole
    content: str | list[ProviderMessageContentBlock]

    @field_validator("content")
    @classmethod
    def _content_must_be_json_safe_without_raw_secret(
        cls,
        value: str | list[ProviderMessageContentBlock],
    ) -> str | list[ProviderMessageContentBlock]:
        serializable_value: str | list[dict[str, object | None]]
        if isinstance(value, str):
            serializable_value = value
        else:
            serializable_value = [block.model_dump(mode="json") for block in value]
        assert_no_raw_secret({"content": serializable_value}, path="$provider_message")
        return value


class ProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: int = Field(..., ge=1)
    run_id: UUID
    provider: str = Field(..., min_length=1, max_length=128)
    api_or_feature: str = Field(..., min_length=1, max_length=128)
    model_resolved: str = Field(..., min_length=1, max_length=256)
    messages: list[ProviderMessage] = Field(..., min_length=1)
    structured_output_schema: dict[str, Any]
    payload_data_class: PayloadDataClass
    provider_compliance_matrix_version: str = Field(..., min_length=1, max_length=128)
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0, le=2)
    safety_settings: dict[str, Any] | None = None
    secret_capability_token: str | None = Field(default=None, min_length=1)

    @field_validator("structured_output_schema")
    @classmethod
    def _structured_output_schema_must_be_valid_json_schema(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("structured_output_schema must be a JSON object.")

        try:
            validator_for(value).check_schema(value)
        except SchemaError as exc:
            raise ValueError("structured_output_schema must be a valid JSON Schema.") from exc

        assert_no_raw_secret(value, path="$provider_request.structured_output_schema")
        return value

    @field_validator("safety_settings")
    @classmethod
    def _safety_settings_must_be_json_safe_without_raw_secret(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        assert_no_raw_secret(value, path="$provider_request.safety_settings")
        return value

    @model_validator(mode="after")
    def _request_payload_must_not_contain_raw_secret(self) -> ProviderRequest:
        payload = self.model_dump(mode="json", exclude={"secret_capability_token"})
        assert_no_raw_secret(payload, path="$provider_request")
        return self


__all__ = [
    "ProviderMessage",
    "ProviderMessageContentBlock",
    "ProviderMessageRole",
    "ProviderRequest",
]

