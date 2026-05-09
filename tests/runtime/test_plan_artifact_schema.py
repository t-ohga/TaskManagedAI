from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.app.domain.artifact.plan import (
    MAX_REPAIR_RETRIES,
    PLAN_ARTIFACT_JSON_SCHEMA,
    PlanArtifact,
    plan_artifact_json_schema,
)
from backend.app.domain.policy.action_class import ALL_ACTION_CLASSES
from backend.app.services.agent_runtime.plan_validator import (
    PlanValidationError,
    validate_plan_artifact,
)


def _valid_plan() -> dict[str, Any]:
    return {
        "summary": "Implement a bounded runtime change.",
        "steps": [
            {
                "description": "Update the runtime service.",
                "target_file": "backend/app/services/agent_runtime/example.py",
                "action_class": "task_write",
                "depends_on": [],
            }
        ],
        "target_files": ["backend/app/services/agent_runtime/example.py"],
        "estimated_complexity": "medium",
        "risks": ["Schema drift"],
        "rollback": "Revert the generated artifact and retry from the previous snapshot.",
    }


def test_valid_plan_artifact_passes_pydantic_and_json_schema_validation() -> None:
    artifact = validate_plan_artifact(_valid_plan())

    assert isinstance(artifact, PlanArtifact)
    assert artifact.summary == "Implement a bounded runtime change."
    assert artifact.steps[0].action_class == "task_write"


def test_summary_longer_than_2000_chars_raises_validation_error() -> None:
    raw = _valid_plan()
    raw["summary"] = "a" * 2001

    with pytest.raises(ValidationError):
        validate_plan_artifact(raw)


def test_steps_longer_than_50_raises_validation_error() -> None:
    raw = _valid_plan()
    raw["steps"] = [
        {
            "description": f"Step {index}",
            "target_file": f"backend/app/services/agent_runtime/example_{index}.py",
            "action_class": "task_write",
            "depends_on": [],
        }
        for index in range(51)
    ]

    with pytest.raises(ValidationError):
        validate_plan_artifact(raw)


@pytest.mark.parametrize(
    "forbidden_path",
    [
        ".env",
        ".git/config",
        ".github/workflows/deploy.yml",
        "migrations/versions/0010_unsafe.py",
    ],
)
def test_forbidden_target_paths_are_rejected(forbidden_path: str) -> None:
    raw = _valid_plan()
    raw["target_files"] = [forbidden_path]

    with pytest.raises(PlanValidationError, match="forbidden path"):
        validate_plan_artifact(raw)


@pytest.mark.parametrize(
    "forbidden",
    [
        ".env",
        ".env.local",
        ".env.production",
        ".git/config",
        ".git/HEAD",
        ".github/workflows/deploy.yml",
        ".github/workflows/test.yml",
        "migrations/0001_init.py",
        "migrations/versions/0001.py",
        "secrets/api.json",
        ".ssh/id_rsa",
        "age/key.age",
        "sops/keys.txt",
        "deploy.pem",
        "server.key",
        "id_rsa",
        "id_ed25519",
    ],
)
def test_validate_plan_artifact_rejects_forbidden_path(forbidden: str) -> None:
    """F-001 (R2): mandatory forbidden path 全件 reject。"""

    raw = {
        "summary": "test",
        "steps": [],
        "target_files": [forbidden],
        "estimated_complexity": "low",
        "rollback": "revert",
    }
    with pytest.raises((ValueError, ValidationError), match=r"forbidden|target_file"):
        validate_plan_artifact(raw)


def test_validate_plan_artifact_rejects_path_traversal() -> None:
    """F-001 (R2): .. を含む path も reject。"""

    raw = {
        "summary": "test",
        "steps": [],
        "target_files": ["../etc/passwd"],
        "estimated_complexity": "low",
        "rollback": "revert",
    }
    with pytest.raises(ValueError, match=r"\.\."):
        validate_plan_artifact(raw)


def test_validate_plan_artifact_rejects_absolute_path() -> None:
    """F-001 (R2): absolute path reject。"""

    raw = {
        "summary": "test",
        "steps": [],
        "target_files": ["/etc/passwd"],
        "estimated_complexity": "low",
        "rollback": "revert",
    }
    with pytest.raises(ValueError, match="relative"):
        validate_plan_artifact(raw)


def test_validate_plan_artifact_accepts_normal_path() -> None:
    """F-001 (R2): 通常の relative path は通る。"""

    raw = {
        "summary": "add login feature",
        "steps": [],
        "target_files": [
            "backend/app/api/auth.py",
            "frontend/app/login/page.tsx",
            "tests/api/test_auth.py",
        ],
        "estimated_complexity": "medium",
        "rollback": "revert PR",
    }
    plan = validate_plan_artifact(raw)
    assert plan.target_files == raw["target_files"]


def test_missing_rollback_raises_validation_error() -> None:
    raw = _valid_plan()
    raw.pop("rollback")

    with pytest.raises(ValidationError):
        validate_plan_artifact(raw)


def test_unknown_plan_step_action_class_raises_validation_error() -> None:
    raw = _valid_plan()
    raw["steps"][0]["action_class"] = "read"

    with pytest.raises(ValidationError):
        validate_plan_artifact(raw)


def test_action_class_schema_uses_adr_00009_seven_values() -> None:
    schema = plan_artifact_json_schema()
    action_class_enum = set(
        schema["$defs"]["PlanStep"]["properties"]["action_class"]["enum"]
    )

    assert action_class_enum == set(ALL_ACTION_CLASSES)


def test_json_schema_export_is_valid() -> None:
    schema = plan_artifact_json_schema()

    Draft202012Validator.check_schema(schema)
    assert schema == PLAN_ARTIFACT_JSON_SCHEMA


def test_max_repair_retries_constant_is_three() -> None:
    assert MAX_REPAIR_RETRIES == 3

