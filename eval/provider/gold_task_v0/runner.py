from __future__ import annotations

import copy
import re
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from jsonschema import validate
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict

from backend.app.domain.provider.adapter import ProviderAdapter
from backend.app.domain.provider.request import ProviderRequest
from backend.app.domain.provider.result import ProviderResult
from backend.app.services.providers._http_helpers import extract_structured_output
from eval.provider.gold_task_v0.dataset import DATASET_VERSION_ID, GoldTaskCase

_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")


class ArtifactBodyRepository(Protocol):
    def get_body(self, artifact_ref: str) -> dict[str, Any] | None:
        ...


class ContractValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    failed: bool
    case_id: str
    dataset_version_id: str
    provider: str
    api_or_feature: str
    mismatches: tuple[str, ...]


def run_gold_task_against_adapter(
    adapter: ProviderAdapter,
    case: GoldTaskCase,
    *,
    http_mock_response: dict[str, Any] | None = None,
    artifact_repo: ArtifactBodyRepository | None = None,
) -> tuple[ProviderResult, ContractValidationResult]:
    if http_mock_response is not None:
        _install_http_mock_response(adapter, http_mock_response)

    request = build_provider_request(adapter, case)
    result = adapter.execute(request)

    mismatches: list[str] = []
    if result.status != case.expected_status:
        mismatches.append(
            f"status mismatch: expected {case.expected_status!r}, got {result.status!r}"
        )

    if result.status == "success":
        structured_output_body = _structured_output_body_for_validation(
            result,
            request,
            case,
            http_mock_response=http_mock_response,
            artifact_repo=artifact_repo,
        )
        if structured_output_body is None:
            mismatches.append(
                "success result must expose structured output body via "
                "artifact_repo, structured_output_body, or test http mock response"
            )
        else:
            try:
                validate(
                    instance=structured_output_body,
                    schema=case.expected_artifact_shape,
                )
            except JsonSchemaValidationError as exc:
                mismatches.append(
                    "structured_output_body shape mismatch: "
                    f"path={list(exc.absolute_path)} validator={exc.validator}"
                )

    if case.expected_redacted_summary_shape is not None:
        try:
            validate(
                instance=result.redacted_response_summary,
                schema=case.expected_redacted_summary_shape,
            )
        except JsonSchemaValidationError as exc:
            mismatches.append(
                "redacted_response_summary shape mismatch: "
                f"path={list(exc.absolute_path)} validator={exc.validator}"
            )

    if _SHA256_HEX_RE.fullmatch(result.provider_request_fingerprint) is None:
        mismatches.append("provider_request_fingerprint is not SHA-256 lowercase hex")

    if result.status == "success" and not result.artifact_ref:
        mismatches.append("success result must include artifact_ref")

    validation = ContractValidationResult(
        passed=len(mismatches) == 0,
        failed=len(mismatches) > 0,
        case_id=case.case_id,
        dataset_version_id=DATASET_VERSION_ID,
        provider=adapter.provider_name(),
        api_or_feature=adapter.api_or_feature(),
        mismatches=tuple(mismatches),
    )
    return result, validation


def build_provider_request(adapter: ProviderAdapter, case: GoldTaskCase) -> ProviderRequest:
    provider = adapter.provider_name()
    template = case.request_template

    model_by_provider = _require_mapping(template, "model_resolved_by_provider")
    payload_class_by_provider = _require_mapping(template, "payload_data_class_by_provider")
    token_by_provider = template.get("secret_capability_token_by_provider", {})
    if not isinstance(token_by_provider, dict):
        raise ValueError("secret_capability_token_by_provider must be an object when present")

    payload: dict[str, Any] = {
        "tenant_id": template.get("tenant_id", 1),
        "run_id": str(uuid5(NAMESPACE_URL, f"{DATASET_VERSION_ID}:{case.case_id}:{provider}")),
        "provider": provider,
        "api_or_feature": adapter.api_or_feature(),
        "model_resolved": _provider_value(model_by_provider, provider, "model_resolved"),
        "messages": copy.deepcopy(template["messages"]),
        "structured_output_schema": copy.deepcopy(template["structured_output_schema"]),
        "payload_data_class": _provider_value(
            payload_class_by_provider,
            provider,
            "payload_data_class",
        ),
        "provider_compliance_matrix_version": template["provider_compliance_matrix_version"],
        "max_tokens": template.get("max_tokens"),
        "temperature": template.get("temperature"),
        "safety_settings": copy.deepcopy(template.get("safety_settings")),
    }

    token = token_by_provider.get(provider)
    if isinstance(token, str) and token:
        payload["secret_capability_token"] = token

    return ProviderRequest.model_validate(payload)


def _structured_output_body_for_validation(
    result: ProviderResult,
    request: ProviderRequest,
    case: GoldTaskCase,
    *,
    http_mock_response: dict[str, Any] | None,
    artifact_repo: ArtifactBodyRepository | None,
) -> dict[str, Any] | None:
    if result.artifact_ref and artifact_repo is not None:
        artifact_body = artifact_repo.get_body(result.artifact_ref)
        if isinstance(artifact_body, dict):
            return artifact_body

    direct_body = getattr(result, "structured_output_body", None)
    if isinstance(direct_body, dict):
        return direct_body

    if http_mock_response is not None:
        payload = http_mock_response.get("payload", http_mock_response)
        if isinstance(payload, dict):
            structured_output, status = extract_structured_output(
                payload,
                request.structured_output_schema,
            )
            if status == "success" and structured_output is not None:
                return structured_output

    # MockProviderAdapter stores the generated structured body as the redacted
    # summary. This fallback is only accepted when that body satisfies the real
    # artifact schema; metadata-only summaries will fail R1-F002 here.
    try:
        validate(instance=result.redacted_response_summary, schema=case.expected_artifact_shape)
    except JsonSchemaValidationError:
        return None
    return dict(result.redacted_response_summary)


def _require_mapping(template: dict[str, Any], key: str) -> dict[str, Any]:
    value = template.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _provider_value(mapping: dict[str, Any], provider: str, field_name: str) -> Any:
    if provider not in mapping:
        raise ValueError(f"{field_name} missing provider override for {provider!r}")
    return mapping[provider]


def _install_http_mock_response(
    adapter: ProviderAdapter,
    http_mock_response: dict[str, Any],
) -> None:
    client = getattr(adapter, "_http_client", None)
    if client is None:
        return

    status_code = int(http_mock_response.get("status_code", 200))
    payload = http_mock_response.get("payload", http_mock_response)
    if not isinstance(payload, dict):
        raise ValueError("http_mock_response payload must be an object")

    set_response = getattr(client, "set_response", None)
    if callable(set_response):
        set_response(status_code, payload)
        return

    response = getattr(client, "response", None)
    if response is not None:
        if hasattr(response, "status_code"):
            response.status_code = status_code
        if hasattr(response, "_payload"):
            response._payload = dict(payload)
            return

    client.response = (status_code, dict(payload))


__all__ = [
    "ArtifactBodyRepository",
    "ContractValidationResult",
    "build_provider_request",
    "run_gold_task_against_adapter",
]

