from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint

from backend.app.db.models.memory_record import MemoryRecord, MemoryRetrievalArtifact
from backend.app.domain.memory.record_kind import ALL_MEMORY_RECORD_KINDS
from backend.app.domain.memory.redaction_status import ALL_MEMORY_REDACTION_STATUSES
from backend.app.schemas.memory import (
    MemoryRecordCreate,
    MemoryRetrievalArtifactCreate,
    MemoryStoreRequest,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = _REPO_ROOT / "migrations" / "versions" / "0032_sp018_memory_records.py"

EXPECTED_MEMORY_RECORD_KINDS = (
    "manual_user",
    "manual_agent",
    "auto_completion",
    "auto_failure",
    "auto_review_finding",
)
EXPECTED_MEMORY_REDACTION_STATUSES = ("redacted", "raw_with_canary_scan_passed")


def _check_definition(model: type[Any], constraint_name: str) -> str:
    for constraint in model.__table__.constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name == constraint_name:
            return str(constraint.sqltext)
    raise AssertionError(f"{constraint_name} not found on {model.__tablename__}.")


def _record_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "project_id": uuid4(),
        "record_kind": "manual_user",
        "content_artifact_ref": "artifact://memory/00000000-0000-4000-8000-000000018001",
        "content_hash": "a" * 64,
        "data_class": "internal",
        "redaction_status": "redacted",
        "sanitizer_version_id": uuid4(),
        "trust_level": "untrusted_content",
        "retention_until": datetime.now(tz=UTC) + timedelta(days=30),
    }
    payload.update(overrides)
    return payload


def _retrieval_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "project_id": uuid4(),
        "memory_record_id": uuid4(),
        "retrieval_artifact_ref": "artifact://memory-retrieval/00000000-0000-4000-8000-000000018002",
        "retrieval_hash": "b" * 64,
        "sanitizer_version_id": uuid4(),
        "trust_level": "untrusted_content",
    }
    payload.update(overrides)
    return payload


def test_memory_record_kind_sources_are_exact() -> None:
    assert ALL_MEMORY_RECORD_KINDS == EXPECTED_MEMORY_RECORD_KINDS

    model_check = _check_definition(MemoryRecord, "memory_records_ck_record_kind")
    migration = _MIGRATION_PATH.read_text(encoding="utf-8")
    for value in EXPECTED_MEMORY_RECORD_KINDS:
        assert value in model_check
        assert value in migration


def test_memory_redaction_status_sources_are_exact() -> None:
    assert ALL_MEMORY_REDACTION_STATUSES == EXPECTED_MEMORY_REDACTION_STATUSES

    model_check = _check_definition(MemoryRecord, "memory_records_ck_redaction_status")
    migration = _MIGRATION_PATH.read_text(encoding="utf-8")
    for value in EXPECTED_MEMORY_REDACTION_STATUSES:
        assert value in model_check
        assert value in migration


def test_memory_schema_is_ref_only_no_raw_content_columns() -> None:
    record_columns = set(MemoryRecord.__table__.columns.keys())
    retrieval_columns = set(MemoryRetrievalArtifact.__table__.columns.keys())
    forbidden = {"raw_content", "redacted_content", "content_jsonb", "payload", "raw_payload"}

    assert forbidden.isdisjoint(record_columns)
    assert forbidden.isdisjoint(retrieval_columns)
    migration = _MIGRATION_PATH.read_text(encoding="utf-8")
    for value in forbidden:
        assert value not in migration


def test_memory_record_schema_rejects_unknown_kind_and_trusted_instruction() -> None:
    with pytest.raises(ValidationError):
        MemoryRecordCreate.model_validate(_record_payload(record_kind="unknown"))

    with pytest.raises(ValidationError):
        MemoryRecordCreate.model_validate(_record_payload(trust_level="trusted_instruction"))


def test_memory_record_schema_rejects_non_sha256_or_naive_retention() -> None:
    with pytest.raises(ValidationError):
        MemoryRecordCreate.model_validate(_record_payload(content_hash="not-sha256"))

    with pytest.raises(ValidationError):
        MemoryRecordCreate.model_validate(
            _record_payload(retention_until=datetime.now().replace(microsecond=0))
        )


def test_memory_store_schema_rejects_caller_owned_record_metadata() -> None:
    payload = {
        "project_id": uuid4(),
        "run_id": uuid4(),
        "record_kind": "manual_user",
        "payload": {"body": "remember this"},
        "retention_until": datetime.now(tz=UTC) + timedelta(days=30),
    }
    MemoryStoreRequest.model_validate(payload)

    for server_owned_field in (
        "content_artifact_ref",
        "content_hash",
        "data_class",
        "redaction_status",
        "sanitizer_version_id",
        "source_artifact_id",
        "trust_level",
    ):
        with pytest.raises(ValidationError):
            MemoryStoreRequest.model_validate(
                payload | {server_owned_field: "caller-owned"}
            )


def test_memory_retrieval_schema_is_untrusted_only() -> None:
    MemoryRetrievalArtifactCreate.model_validate(_retrieval_payload())

    with pytest.raises(ValidationError):
        MemoryRetrievalArtifactCreate.model_validate(
            _retrieval_payload(trust_level="validated_artifact")
        )

    check = _check_definition(
        MemoryRetrievalArtifact,
        "memory_retrieval_artifacts_ck_trust_level_untrusted",
    )
    assert "untrusted_content" in check
