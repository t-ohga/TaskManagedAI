from __future__ import annotations

import posixpath
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.domain.policy.action_class import ActionClass

EstimatedComplexity = Literal["low", "medium", "high"]

MAX_REPAIR_RETRIES: int = 3

_FORBIDDEN_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\.env(\.[a-zA-Z0-9_-]+)?$"),
    re.compile(r"^\.git(/.*)?$"),
    re.compile(r"^\.github/workflows(/.*)?$"),
    re.compile(r"^migrations(/.*)?$"),
    re.compile(r"^secrets(/.*)?$"),
    re.compile(r"^\.ssh(/.*)?$"),
    re.compile(r"^age(/.*)?$"),
    re.compile(r"^sops(/.*)?$"),
    re.compile(r".+\.pem$"),
    re.compile(r".+\.key$"),
    re.compile(r".+\.age$"),
    re.compile(r"^id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$"),
)


def _normalize_target_file(path: str) -> str:
    """target_file を normalize するが、leading dot は維持する。"""

    if not isinstance(path, str):
        raise ValueError(f"target_file must be str, got {type(path).__name__}")

    normalized = path.replace("\\", "/").strip()
    if not normalized:
        raise ValueError("target_file must not be empty")
    if "\x00" in normalized:
        raise ValueError("target_file contains null byte")
    if normalized.startswith("/"):
        raise ValueError(f"target_file must be relative path: {path!r}")

    parts = normalized.split("/")
    if ".." in parts:
        raise ValueError(f"target_file must not contain '..' segment: {path!r}")

    return posixpath.normpath(normalized)


def _check_forbidden_path(target_file: str) -> None:
    """forbidden path patterns に該当すれば ValueError。

    F-001 (R2): leading dot を維持したまま regex 評価する。
    """

    normalized = _normalize_target_file(target_file)
    for pattern in _FORBIDDEN_PATH_PATTERNS:
        if pattern.match(normalized):
            raise ValueError(
                f"target_file matches forbidden path pattern: {target_file!r}"
            )


def normalize_plan_path(path: str) -> str:
    return path.replace("\\", "/").strip()


def is_forbidden_plan_path(path: str) -> bool:
    normalized = _normalize_target_file(path)
    return any(pattern.match(normalized) for pattern in _FORBIDDEN_PATH_PATTERNS)


def assert_allowed_plan_path(path: str, *, field_name: str = "target_file") -> str:
    try:
        _check_forbidden_path(path)
    except ValueError as exc:
        if field_name != "target_file":
            raise ValueError(str(exc).replace("target_file", field_name, 1)) from exc
        raise
    return path


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(..., min_length=1, max_length=2000)
    target_file: str | None = Field(default=None, min_length=1, max_length=512)
    action_class: ActionClass
    depends_on: list[int] = Field(default_factory=list, max_length=50)

    @field_validator("target_file")
    @classmethod
    def _target_file_must_be_allowed(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return assert_allowed_plan_path(value, field_name="target_file")

    @field_validator("depends_on")
    @classmethod
    def _depends_on_indices_must_be_non_negative(cls, value: list[int]) -> list[int]:
        if any(index < 0 for index in value):
            raise ValueError("depends_on indices must be zero or greater.")
        return value


class PlanArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(..., min_length=1, max_length=2000)
    steps: list[PlanStep] = Field(default_factory=list, max_length=50)
    target_files: list[str] = Field(default_factory=list, max_length=100)
    estimated_complexity: EstimatedComplexity
    risks: list[str] = Field(default_factory=list, max_length=50)
    rollback: str = Field(..., min_length=1, max_length=4000)

    @field_validator("target_files")
    @classmethod
    def _target_files_must_be_allowed(cls, value: list[str]) -> list[str]:
        for path in value:
            assert_allowed_plan_path(path, field_name="target_files")
        return value

    @field_validator("risks")
    @classmethod
    def _risks_must_not_be_blank(cls, value: list[str]) -> list[str]:
        if any(not risk.strip() for risk in value):
            raise ValueError("risks must not contain blank items.")
        return value


def plan_artifact_json_schema() -> dict[str, Any]:
    return PlanArtifact.model_json_schema()


PLAN_ARTIFACT_JSON_SCHEMA: dict[str, Any] = plan_artifact_json_schema()

__all__ = [
    "EstimatedComplexity",
    "MAX_REPAIR_RETRIES",
    "PLAN_ARTIFACT_JSON_SCHEMA",
    "PlanArtifact",
    "PlanStep",
    "_FORBIDDEN_PATH_PATTERNS",
    "_check_forbidden_path",
    "_normalize_target_file",
    "assert_allowed_plan_path",
    "is_forbidden_plan_path",
    "normalize_plan_path",
    "plan_artifact_json_schema",
]

