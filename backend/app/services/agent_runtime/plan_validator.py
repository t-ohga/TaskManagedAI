from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from backend.app.domain.artifact.plan import (
    PlanArtifact,
    _check_forbidden_path,
    _normalize_target_file,
)


class PlanValidationError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _iter_raw_target_paths(raw: Mapping[str, Any]) -> Iterator[tuple[str, Any]]:
    target_files = raw.get("target_files")
    if isinstance(target_files, list):
        for index, target_file in enumerate(target_files):
            yield (f"target_files[{index}]", target_file)

    steps = raw.get("steps")
    if isinstance(steps, list):
        for index, step in enumerate(steps):
            if isinstance(step, Mapping) and "target_file" in step:
                yield (f"steps[{index}].target_file", step.get("target_file"))


def _assert_no_forbidden_paths(raw: Mapping[str, Any]) -> None:
    for field_name, target_path in _iter_raw_target_paths(raw):
        try:
            _check_forbidden_path(target_path)
        except ValueError as exc:
            raise PlanValidationError(f"{field_name}: {exc}") from exc


def validate_plan_artifact(raw: dict[str, Any]) -> PlanArtifact:
    if not isinstance(raw, dict):
        raise PlanValidationError("plan artifact raw payload must be a JSON object.")

    _assert_no_forbidden_paths(raw)

    try:
        artifact = PlanArtifact.model_validate(raw)
    except PydanticValidationError:
        raise

    schema = PlanArtifact.model_json_schema()
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(artifact.model_dump(exclude_none=True))
    except (JsonSchemaValidationError, SchemaError) as exc:
        raise PlanValidationError(f"plan artifact JSON Schema validation failed: {exc}") from exc

    _assert_no_forbidden_paths(artifact.model_dump(exclude_none=True))
    return artifact


__all__ = [
    "PlanValidationError",
    "_check_forbidden_path",
    "_normalize_target_file",
    "validate_plan_artifact",
]

